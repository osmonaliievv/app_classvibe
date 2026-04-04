from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from . import models, schemas
from .database import get_db
from .firebase_service import verify_firebase_id_token

from .utils import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    validate_username,
    verify_password as utils_verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
ONLINE_DELTA_SECONDS = 120


# ---------- Вспомогательные ----------

def get_password_hash(password: str) -> str:
    return hash_password(password)

def verify_password(plain: str, hashed: str) -> bool:
    return utils_verify_password(plain, hashed)

def _get_registration_or_404(db: Session, registration_id: str) -> models.RegistrationSession:
    reg = db.query(models.RegistrationSession).filter(
        models.RegistrationSession.id == registration_id
    ).first()
    if not reg:
        raise HTTPException(status_code=404, detail="Сессия регистрации не найдена")
    return reg

def _find_user_by_identifier(db: Session, identifier: str) -> models.User | None:
    return db.query(models.User).filter(
        (models.User.email == identifier)
        | (models.User.phone == identifier)
        | (models.User.username == identifier)
    ).first()

def get_current_user(
    authorization: str = Header(None),
    db: Session = Depends(get_db),
) -> models.User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Необходимо передать токен")

    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)

    if not payload or "sub" not in payload or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Невалидный или просроченный токен")

    user = db.query(models.User).filter(models.User.id == int(payload["sub"])).first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    user.last_seen = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user

def is_user_online(user: models.User) -> bool:
    if not getattr(user, "last_seen", None):
        return False
    return (datetime.utcnow() - user.last_seen).total_seconds() <= ONLINE_DELTA_SECONDS


# ---------- Логин ----------

@router.post("/login", response_model=schemas.LoginResponse)
def login(data: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = _find_user_by_identifier(db, data.identifier)
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    user.last_seen = datetime.utcnow()
    db.commit()
    db.refresh(user)

    return schemas.LoginResponse(
        user=user,
        token=schemas.Token(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
        ),
    )


# ---------- Обновление токена ----------

@router.post("/refresh", response_model=schemas.Token)
def refresh_access_token(data: schemas.RefreshRequest, db: Session = Depends(get_db)):
    payload = decode_access_token(data.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Невалидный refresh token")

    user = db.query(models.User).filter(
        models.User.id == int(payload["sub"]),
        models.User.is_active == True,
    ).first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    return schemas.Token(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


# ---------- Регистрация: шаг 1 — BIO ----------

@router.post("/register/bio", response_model=schemas.RegistrationSessionResponse)
def register_bio(data: schemas.RegisterBioRequest, db: Session = Depends(get_db)):
    reg = models.RegistrationSession(
        id=str(uuid.uuid4()),
        first_name=data.first_name,
        last_name=data.last_name,
        birth_date=data.birth_date,
        gender=data.gender,
    )
    db.add(reg)
    db.commit()
    db.refresh(reg)
    return schemas.RegistrationSessionResponse(registration_id=reg.id)


# ---------- Регистрация: шаг 2 — роль ----------

@router.post("/register/role", response_model=schemas.RegistrationSessionResponse)
def register_role(data: schemas.RegisterRoleRequest, db: Session = Depends(get_db)):
    reg = _get_registration_or_404(db, data.registration_id)
    reg.role = data.role
    reg.updated_at = datetime.utcnow()
    db.commit()
    return schemas.RegistrationSessionResponse(registration_id=reg.id)


# ---------- Регистрация: шаг 3 — контакт ----------

@router.post("/register/contact", response_model=schemas.RegistrationSessionResponse)
def register_contact(data: schemas.RegisterContactRequest, db: Session = Depends(get_db)):
    reg = _get_registration_or_404(db, data.registration_id)

    # Проверяем уникальность
    if data.contact_type == models.ContactTypeEnum.email:
        existing = db.query(models.User).filter(models.User.email == data.contact_value).first()
    else:
        existing = db.query(models.User).filter(models.User.phone == data.contact_value).first()

    if existing:
        raise HTTPException(status_code=400, detail="Этот контакт уже используется")

    reg.contact_type = data.contact_type
    reg.contact_value = data.contact_value
    reg.is_contact_verified = False
    reg.updated_at = datetime.utcnow()
    db.commit()

    # ✅ Верификацию отправляет Firebase SDK на клиенте (React Native)
    # Бэкенд только сохраняет контакт и ждёт firebase_token на следующем шаге
    return schemas.RegistrationSessionResponse(registration_id=reg.id)


# ---------- Регистрация: шаг 4 — верификация через Firebase token ----------

@router.post("/register/verify-firebase", response_model=schemas.RegistrationSessionResponse)
def verify_firebase(
    data: schemas.VerifyFirebaseTokenRequest,
    db: Session = Depends(get_db),
):
    """
    Клиент прошёл верификацию через Firebase (SMS или Email),
    получил idToken и отправляет его сюда для подтверждения.
    """
    reg = _get_registration_or_404(db, data.registration_id)

    try:
        decoded = verify_firebase_id_token(data.firebase_id_token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Проверяем совпадение контакта
    firebase_phone = decoded.get("phone_number")
    firebase_email = decoded.get("email")

    if reg.contact_type == models.ContactTypeEnum.phone:
        if firebase_phone != reg.contact_value:
            raise HTTPException(
                status_code=400,
                detail=f"Телефон в токене ({firebase_phone}) не совпадает с сессией",
            )
    elif reg.contact_type == models.ContactTypeEnum.email:
        if (firebase_email or "").lower() != reg.contact_value.lower():
            raise HTTPException(
                status_code=400,
                detail=f"Email в токене ({firebase_email}) не совпадает с сессией",
            )

    # Сохраняем firebase_uid в сессии для финального шага
    reg.is_contact_verified = True
    reg.updated_at = datetime.utcnow()

    # Можно сохранить uid во временное поле, если хочешь связать с User позже
    # reg.firebase_uid = decoded["uid"]
    db.commit()

    return schemas.RegistrationSessionResponse(registration_id=reg.id)


# ---------- Регистрация: шаг 5 — пароль ----------

@router.post("/register/password", response_model=schemas.RegistrationSessionResponse)
def register_password(data: schemas.RegisterPasswordRequest, db: Session = Depends(get_db)):
    reg = _get_registration_or_404(db, data.registration_id)

    if data.password != data.password_confirm:
        raise HTTPException(status_code=400, detail="Пароли не совпадают")
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="Пароль должен быть не короче 8 символов")

    reg.password_hash = get_password_hash(data.password)
    reg.updated_at = datetime.utcnow()
    db.commit()
    return schemas.RegistrationSessionResponse(registration_id=reg.id)


# ---------- Проверка username ----------

@router.get("/username-check", response_model=schemas.UsernameCheckResponse)
def username_check(username: str, db: Session = Depends(get_db)):
    if not validate_username(username):
        return schemas.UsernameCheckResponse(username=username, available=False)
    existing = db.query(models.User).filter(models.User.username == username).first()
    return schemas.UsernameCheckResponse(username=username, available=(existing is None))


# ---------- Регистрация: финал ----------

@router.post("/register/username", response_model=schemas.LoginResponse)
def register_username(data: schemas.RegisterUsernameRequest, db: Session = Depends(get_db)):
    reg_id = data.session_id or data.registration_id
    if not reg_id:
        raise HTTPException(status_code=400, detail="Не передан session_id / registration_id")

    reg = _get_registration_or_404(db, reg_id)

    if not reg.is_contact_verified:
        raise HTTPException(status_code=400, detail="Сначала подтвердите контакт через Firebase")

    missing = [f for f in ("first_name","last_name","birth_date","gender","role","password_hash") if getattr(reg, f) is None]
    if missing:
        raise HTTPException(status_code=400, detail=f"Отсутствуют данные: {', '.join(missing)}")

    if not validate_username(data.username):
        raise HTTPException(status_code=400, detail="Недопустимые символы в username")

    if db.query(models.User).filter(models.User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Имя пользователя уже занято")

    reg.username = data.username
    reg.is_completed = True
    reg.updated_at = datetime.utcnow()

    user = models.User(
        first_name=reg.first_name,
        last_name=reg.last_name,
        birth_date=reg.birth_date,
        gender=reg.gender,
        role=reg.role,
        username=reg.username,
        password_hash=reg.password_hash,
        is_verified=True,
        status=reg.role.value,
        last_seen=datetime.utcnow(),
    )

    if reg.contact_type == models.ContactTypeEnum.email:
        user.email = reg.contact_value
    elif reg.contact_type == models.ContactTypeEnum.phone:
        user.phone = reg.contact_value

    db.add(user)
    db.commit()
    db.refresh(user)

    return schemas.LoginResponse(
        user=user,
        token=schemas.Token(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
        ),
    )


# ---------- Забыл пароль ----------

@router.post("/forgot-password", response_model=schemas.SimpleMessage)
def forgot_password(data: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)):
    # Всегда отвечаем одинаково (безопасность)
    return schemas.SimpleMessage(message="Если аккаунт существует, будут отправлены инструкции.")


@router.post("/forgot-password/confirm", response_model=schemas.SimpleMessage)
def forgot_password_confirm(
    data: schemas.ForgotPasswordConfirmFirebaseRequest,
    db: Session = Depends(get_db),
):
    """
    Клиент верифицировал телефон/email через Firebase,
    получил idToken и отправляет его вместе с новым паролем.
    """
    try:
        decoded = verify_firebase_id_token(data.firebase_id_token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    firebase_phone = decoded.get("phone_number")
    firebase_email = decoded.get("email")

    user = None
    if firebase_phone:
        user = db.query(models.User).filter(models.User.phone == firebase_phone).first()
    if not user and firebase_email:
        user = db.query(models.User).filter(models.User.email == firebase_email).first()

    if not user:
        raise HTTPException(status_code=400, detail="Пользователь не найден")

    if data.new_password != data.new_password_confirm:
        raise HTTPException(status_code=400, detail="Пароли не совпадают")
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="Пароль должен быть не короче 8 символов")

    user.password_hash = get_password_hash(data.new_password)
    db.commit()

    return schemas.SimpleMessage(message="Пароль успешно изменён. Теперь войдите в аккаунт.")


# ---------- /auth/me ----------

@router.get("/me", response_model=schemas.UserBase)
def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user