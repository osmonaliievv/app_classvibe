import random
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import jwt
from passlib.context import CryptContext

from .config import SECRET_KEY, JWT_ALGORITHM, get_access_token_expires_delta
from .models import RoleEnum  # для role_to_status

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto",
)


# ---------- Пароли ----------


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


# ---------- JWT токены ----------

# Время жизни Refresh токена — 30 дней (как в Instagram)
REFRESH_TOKEN_EXPIRE_DAYS = 30


def create_access_token(subject: str | int) -> str:
    expires_delta: timedelta = get_access_token_expires_delta()
    to_encode = {
        "sub": str(subject),
        "exp": datetime.utcnow() + expires_delta,
        "type": "access"  # Добавляем тип токена
    }
    return jwt.encode(to_encode, SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(subject: str | int) -> str:

    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {
        "sub": str(subject),
        "exp": expire,
        "type": "refresh"  # Четко помечаем, что это refresh
    }
    return jwt.encode(to_encode, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


# ---------- 4-значный код ----------


def generate_verification_code() -> str:
    return f"{random.randint(0, 9999):04d}"


# ---------- username validation ----------

# Разрешаем латиницу, цифры, точку и подчёркивание
USERNAME_REGEX = re.compile(r"^[A-Za-z0-9_.]+$")


def validate_username(username: str) -> bool:

    if len(username) < 3 or len(username) > 50:
        return False
    return USERNAME_REGEX.fullmatch(username) is not None


def is_valid_username(username: str) -> bool:

    return validate_username(username)


# ---------- роль -> статус ----------

_ROLE_STATUS_MAP = {
    RoleEnum.pupil: "Ученик",
    RoleEnum.teacher: "Учитель",
    RoleEnum.student: "Студент",
}


def role_to_status(role: Optional[RoleEnum]) -> Optional[str]:
    if not role:
        return None
    return _ROLE_STATUS_MAP.get(role)


# Добавить в конец utils.py
def format_local_time(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        import datetime as dt_module
        return dt.replace(tzinfo=dt_module.timezone.utc)
    return dt
