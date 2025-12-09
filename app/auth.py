# app/auth.py

from datetime import datetime, timedelta
import uuid

from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session

from . import schemas, models
from .database import get_db
from .utils import (
    hash_password,
    verify_password as utils_verify_password,
    create_access_token,
    generate_verification_code,
    decode_access_token,
    validate_username,
)

router = APIRouter(prefix="/auth", tags=["auth"])

VERIFICATION_CODE_LIFETIME_SECONDS = 5 * 60  # 5 минут
RESEND_CODE_COOLDOWN_SECONDS = 60           # 1 минута
ONLINE_DELTA_SECONDS = 120                  # сколько секунд считаем пользователя online


# ---------- Вспомогательные функции ----------


def get_password_hash(password: str) -> str:
    return hash_password(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return utils_verify_password(plain_password, hashed_password)


def _get_registration_or_404(
    db: Session,
    registration_id: str,
) -> models.RegistrationSession:
    reg = (
        db.query(models.RegistrationSession)
        .filter(models.RegistrationSession.id == registration_id)
        .first()
    )
    if not reg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сессия регистрации не найдена",
        )
    return reg


def _send_verification_code(
    contact_type: models.ContactTypeEnum,
    contact_value: str,
    code: str,
):
    """
    Заглушка отправки кода.
    Сейчас просто печатаем в консоль, чтобы было сложно пропустить.
    """
    print("\n" + "=" * 70, flush=True)
    print(
        f"[VERIFICATION CODE] type={contact_type.value} value={contact_value}  CODE={code}",
        flush=True,
    )
    print("=" * 70 + "\n", flush=True)


def get_current_user(
    authorization: str = Header(None),
    db: Session = Depends(get_db),
) -> models.User:
    """
    Получение текущего пользователя по заголовку Authorization: Bearer <token>.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходимо передать токен в заголовке Authorization",
        )

    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)

    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный или просроченный токен",
        )

    user_id = int(payload["sub"])
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден",
        )

    # обновляем last_seen
    now = datetime.utcnow()
    user.last_seen = now
    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def is_user_online(user: models.User) -> bool:
    """
    Проверка, в онлайне ли пользователь по last_seen.
    """
    if not getattr(user, "last_seen", None):
        return False
    delta = datetime.utcnow() - user.last_seen
    return delta.total_seconds() <= ONLINE_DELTA_SECONDS


# ---------- Логин ----------


@router.post("/login", response_model=schemas.LoginResponse)
def login(data: schemas.LoginRequest, db: Session = Depends(get_db)):
    """
    Логин по email / телефону / username + пароль.
    """
    user = (
        db.query(models.User)
        .filter(
            (models.User.email == data.identifier)
            | (models.User.phone == data.identifier)
            | (models.User.username == data.identifier)
        )
        .first()
    )
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )

    user.last_seen = datetime.utcnow()
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id)
    return schemas.LoginResponse(user=user, token=schemas.Token(access_token=token))


# ---------- Регистрация: шаг 1 — BIO ----------


@router.post("/register/bio", response_model=schemas.RegistrationSessionResponse)
def register_bio(
    data: schemas.RegisterBioRequest,
    db: Session = Depends(get_db),
):
    """
    Создаём сессию регистрации и заполняем имя, фамилию, дату рождения, пол.
    """
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
def register_role(
    data: schemas.RegisterRoleRequest,
    db: Session = Depends(get_db),
):
    reg = _get_registration_or_404(db, data.registration_id)
    reg.role = data.role
    reg.updated_at = datetime.utcnow()
    db.commit()
    return schemas.RegistrationSessionResponse(registration_id=reg.id)


# ---------- Регистрация: шаг 3 — контакт ----------


@router.post("/register/contact", response_model=schemas.RegistrationSessionResponse)
def register_contact(
    data: schemas.RegisterContactRequest,
    db: Session = Depends(get_db),
):
    reg = _get_registration_or_404(db, data.registration_id)

    # проверяем уникальность контакта
    if data.contact_type == models.ContactTypeEnum.email:
        existing = (
            db.query(models.User)
            .filter(models.User.email == data.contact_value)
            .first()
        )
    else:
        existing = (
            db.query(models.User)
            .filter(models.User.phone == data.contact_value)
            .first()
        )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот контакт уже используется",
        )

    reg.contact_type = data.contact_type
    reg.contact_value = data.contact_value

    code = generate_verification_code()
    reg.verification_code_hash = get_password_hash(code)
    reg.verification_code_expires_at = datetime.utcnow() + timedelta(
        seconds=VERIFICATION_CODE_LIFETIME_SECONDS
    )
    reg.last_code_sent_at = datetime.utcnow()
    reg.is_contact_verified = False
    reg.updated_at = datetime.utcnow()
    db.commit()

    _send_verification_code(reg.contact_type, reg.contact_value, code)

    return schemas.RegistrationSessionResponse(registration_id=reg.id)


# ---------- Регистрация: повторная отправка кода ----------


@router.post("/register/resend-code", response_model=schemas.RegistrationSessionResponse)
def resend_code(
    data: schemas.ResendCodeRequest,
    db: Session = Depends(get_db),
):
    reg = _get_registration_or_404(db, data.registration_id)

    now = datetime.utcnow()
    if reg.last_code_sent_at and (
        now - reg.last_code_sent_at
    ).total_seconds() < RESEND_CODE_COOLDOWN_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Повторная отправка пока недоступна",
        )

    if not reg.contact_type or not reg.contact_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сначала нужно указать контакт",
        )

    code = generate_verification_code()
    reg.verification_code_hash = get_password_hash(code)
    reg.verification_code_expires_at = now + timedelta(
        seconds=VERIFICATION_CODE_LIFETIME_SECONDS
    )
    reg.last_code_sent_at = now
    reg.updated_at = now
    db.commit()

    _send_verification_code(reg.contact_type, reg.contact_value, code)

    return schemas.RegistrationSessionResponse(registration_id=reg.id)


# ---------- Регистрация: проверка кода ----------


@router.post("/register/verify-code", response_model=schemas.RegistrationSessionResponse)
def verify_code(
    data: schemas.VerifyCodeRequest,
    db: Session = Depends(get_db),
):
    reg = _get_registration_or_404(db, data.registration_id)

    if not reg.verification_code_hash or not reg.verification_code_expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Код ещё не был отправлен",
        )

    if datetime.utcnow() > reg.verification_code_expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Код истёк, запросите новый",
        )

    if not verify_password(data.code, reg.verification_code_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный код",
        )

    reg.is_contact_verified = True
    reg.updated_at = datetime.utcnow()
    db.commit()

    return schemas.RegistrationSessionResponse(registration_id=reg.id)


# ---------- Регистрация: пароль ----------


@router.post("/register/password", response_model=schemas.RegistrationSessionResponse)
def register_password(
    data: schemas.RegisterPasswordRequest,
    db: Session = Depends(get_db),
):
    reg = _get_registration_or_404(db, data.registration_id)

    if data.password != data.password_confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пароли не совпадают",
        )

    if len(data.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пароль должен быть не короче 8 символов",
        )

    reg.password_hash = get_password_hash(data.password)
    reg.updated_at = datetime.utcnow()
    db.commit()

    return schemas.RegistrationSessionResponse(registration_id=reg.id)


# ---------- Проверка username ----------


@router.get("/username-check", response_model=schemas.UsernameCheckResponse)
def username_check(
    username: str,
    db: Session = Depends(get_db),
):
    if not validate_username(username):
        return schemas.UsernameCheckResponse(username=username, available=False)

    existing = (
        db.query(models.User)
        .filter(models.User.username == username)
        .first()
    )
    return schemas.UsernameCheckResponse(
        username=username,
        available=(existing is None),
    )


# ---------- Регистрация: финал — username + создание пользователя ----------


@router.post("/register/username", response_model=schemas.LoginResponse)
def register_username(
    data: schemas.RegisterUsernameRequest,
    db: Session = Depends(get_db),
):

    reg_id = data.session_id or data.registration_id
    if not reg_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не передан session_id / registration_id",
        )

    reg = _get_registration_or_404(db, reg_id)

    if not reg.is_contact_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сначала подтвердите контакт",
        )

    # проверяем, что все обязательные поля заполнены
    required_fields = (
        "first_name",
        "last_name",
        "birth_date",
        "gender",
        "role",
        "password_hash",
    )
    missing = [f for f in required_fields if getattr(reg, f) is None]

    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Регистрация не завершена: отсутствуют данные в полях: "
                + ", ".join(missing)
            ),
        )

    # проверяем username
    if not validate_username(data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Имя пользователя может содержать только английские буквы, "
                "цифры, '.', и '_'"
            ),
        )

    existing = (
        db.query(models.User)
        .filter(models.User.username == data.username)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Имя пользователя уже занято",
        )

    # сохраняем username в сессии
    reg.username = data.username
    reg.is_completed = True
    reg.updated_at = datetime.utcnow()
    db.add(reg)

    # создаём пользователя
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

    token_str = create_access_token(user.id)
    token = schemas.Token(access_token=token_str)
    return schemas.LoginResponse(user=user, token=token)


# ---------- Забыл пароль (заглушка) ----------


@router.post("/forgot-password", response_model=schemas.SimpleMessage)
def forgot_password(
    data: schemas.ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    user = (
        db.query(models.User)
        .filter(
            (models.User.email == data.identifier)
            | (models.User.phone == data.identifier)
            | (models.User.username == data.identifier)
        )
        .first()
    )
    if not user:
        # Не палим, существует ли пользователь
        return schemas.SimpleMessage(
            message="Если аккаунт существует, будут отправлены инструкции.",
        )

    print(f"[DEBUG] Запрос на сброс пароля для пользователя id={user.id}")
    return schemas.SimpleMessage(
        message="Если аккаунт существует, будут отправлены инструкции.",
    )


# ---------- /auth/me ----------


@router.get("/me", response_model=schemas.UserBase)
def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user
