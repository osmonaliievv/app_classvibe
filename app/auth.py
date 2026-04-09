from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from . import models, schemas
from .database import get_db
from .twilio_service import send_verification_code, check_verification_code

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


def _normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not phone.startswith("+"):
        raise HTTPException(status_code=400, detail="Телефон должен быть в формате E.164, например +393331234567")
    return phone


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

    if data.contact_type == models.ContactTypeEnum.email:
        existing = db.query(models.User).filter(models.User.email == data.contact_value).first()
        reg.contact_value = data.contact_value.strip().lower()
    else:
        normalized_phone = _normalize_phone(data.contact_value)
        existing = db.query(models.User).filter(models.User.phone == normalized_phone).first()
        reg.contact_value = normalized_phone

    if existing:
        raise HTTPException(status_code=400, detail="Этот контакт уже используется")

    reg.contact_type = data.contact_type
    reg.is_contact_verified = False
    reg.updated_at = datetime.utcnow()
    db.commit()

    return schemas.RegistrationSessionResponse(registration_id=reg.id)


# ---------- Отправка SMS-кода через Twilio Verify ----------

@router.post("/verify/send", response_model=schemas.RegistrationSessionResponse)
def verify_send(data: schemas.SendCodeRequest, db: Session = Depends(get_db)):
    reg = _get_registration_or_404(db, data.registration_id)

    if reg.contact_type != models.ContactTypeEnum.phone:
        raise HTTPException(status_code=400, detail="SMS-верификация доступна только для телефона")

    phone = _normalize_phone(data.phone)

    if reg.contact_value != phone:
        raise HTTPException(status_code=400, detail="Телефон не совпадает с contact_value в сессии")

    send_verification_code(phone)

    reg.last_code_sent_at = datetime.utcnow()
    reg.updated_at = datetime.utcnow()
    db.commit()

    return schemas.RegistrationSessionResponse(registration_id=reg.id)


# ---------- Проверка SMS-кода через Twilio Verify ----------

@router.post("/verify/check", response_model=schemas.RegistrationSessionResponse)
def verify_check(data: schemas.VerifyPhoneCodeRequest, db: Session = Depends(get_db)):
    reg = _get_registration_or_404(db, data.registration_id)

    if reg.contact_type != models.ContactTypeEnum.phone:
        raise HTTPException(status_code=400, detail="SMS-верификация доступна только для телефона")

    phone = _normalize_phone(data.phone)

    if reg.contact_value != phone:
        raise HTTPException(status_code=400, detail="Телефон не совпадает с contact_value в сессии")

    result = check_verification_code(phone, data.code)

    if result.status != "approved":
        raise HTTPException(status_code=400, detail="Неверный или просроченный код")

    reg.is_contact_verified = True
    reg.updated_at = datetime.utcnow()
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
        raise HTTPException(status_code=400, detail="Сначала подтвердите телефон через SMS-код")

    missing = [f for f in ("first_name", "last_name", "birth_date", "gender", "role", "password_hash") if getattr(reg, f) is None]
    if missing:
        raise HTTPException(status_code=400, detail=f"Отсутствуют данные: {', '.join(missing)}")

    if not validate_username(data.username):
        raise HTTPException(status_code=400, detail="Недопустимые символы в username")

    if db.query(models.User).filter(models.User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Имя пользователя уже занято")

    # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА КОНТАКТА ПЕРЕД СОЗДАНИЕМ USER
    if reg.contact_type == models.ContactTypeEnum.phone:
        existing_phone_user = db.query(models.User).filter(models.User.phone == reg.contact_value).first()
        if existing_phone_user:
            raise HTTPException(status_code=400, detail="Пользователь с таким телефоном уже существует")

    if reg.contact_type == models.ContactTypeEnum.email:
        existing_email_user = db.query(models.User).filter(models.User.email == reg.contact_value).first()
        if existing_email_user:
            raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")

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

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

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
    return schemas.SimpleMessage(message="Если аккаунт существует, будут отправлены инструкции.")


# ---------- /auth/me ----------

@router.get("/me", response_model=schemas.UserBase)
def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user