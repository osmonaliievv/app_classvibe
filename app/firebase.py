# app/firebase.py

import os
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth
from fastapi import HTTPException, status

_firebase_initialized = False


def _init_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return

    cert_path = os.getenv("FIREBASE_SERVICE_ACCOUNT", "firebase_service_account.json")

    if not os.path.exists(cert_path):
        raise RuntimeError(
            f"Firebase service account file not found: '{cert_path}'. "
            "Скачай его в Firebase Console → Project Settings → Service Accounts → Generate new private key "
            "и положи в корень проекта как 'firebase_service_account.json', "
            "или укажи путь через переменную окружения FIREBASE_SERVICE_ACCOUNT."
        )

    cred = credentials.Certificate(cert_path)
    firebase_admin.initialize_app(cred)
    _firebase_initialized = True


def verify_firebase_token(id_token: str) -> dict:

    _init_firebase()

    try:
        decoded = firebase_auth.verify_id_token(id_token)
        return decoded
    except firebase_auth.ExpiredIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase токен просрочен",
        )
    except firebase_auth.InvalidIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный Firebase токен",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ошибка верификации Firebase токена",
        )