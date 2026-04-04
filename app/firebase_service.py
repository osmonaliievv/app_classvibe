from pathlib import Path
import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

_SERVICE_ACCOUNT_PATH = os.getenv(
    "FIREBASE_SERVICE_ACCOUNT_PATH",
    str(BASE_DIR / "serviceAccountKey.json"),
)

if not firebase_admin._apps:
    cred = credentials.Certificate(_SERVICE_ACCOUNT_PATH)
    firebase_admin.initialize_app(cred)

print("=== FIREBASE INIT OK ===", flush=True)


def verify_firebase_id_token(id_token: str) -> dict:
    """
    Верифицирует Firebase ID token, полученный с клиента (React Native).
    Возвращает decoded token с uid, phone_number, email и т.д.
    """
    try:
        decoded = firebase_auth.verify_id_token(id_token)
        print(f"[FIREBASE] Token verified: uid={decoded['uid']}", flush=True)
        return decoded
    except firebase_auth.ExpiredIdTokenError:
        raise ValueError("Firebase token истёк")
    except firebase_auth.InvalidIdTokenError:
        raise ValueError("Невалидный Firebase token")
    except Exception as e:
        raise ValueError(f"Ошибка верификации Firebase token: {str(e)}")


def get_or_create_firebase_user_by_phone(phone: str) -> firebase_auth.UserRecord:
    """Получить или создать Firebase пользователя по телефону."""
    try:
        user = firebase_auth.get_user_by_phone_number(phone)
        print(f"[FIREBASE] Found user by phone: {user.uid}", flush=True)
        return user
    except firebase_auth.UserNotFoundError:
        user = firebase_auth.create_user(phone_number=phone)
        print(f"[FIREBASE] Created user by phone: {user.uid}", flush=True)
        return user


def get_or_create_firebase_user_by_email(email: str) -> firebase_auth.UserRecord:
    """Получить или создать Firebase пользователя по email."""
    try:
        user = firebase_auth.get_user_by_email(email)
        print(f"[FIREBASE] Found user by email: {user.uid}", flush=True)
        return user
    except firebase_auth.UserNotFoundError:
        user = firebase_auth.create_user(email=email)
        print(f"[FIREBASE] Created user by email: {user.uid}", flush=True)
        return user


def create_custom_token(uid: str) -> str:
    """Создаёт Firebase Custom Token для клиента."""
    token = firebase_auth.create_custom_token(uid)
    return token.decode("utf-8") if isinstance(token, bytes) else token