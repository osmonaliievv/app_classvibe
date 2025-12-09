# app/push.py
import os
from typing import Optional, Dict

import firebase_admin
from firebase_admin import credentials, messaging

_fcm_initialized = False


def _init_fcm() -> bool:
    global _fcm_initialized
    if _fcm_initialized:
        return True

    path = os.getenv("FIREBASE_CREDENTIALS_FILE")
    if not path or not os.path.exists(path):
        print("[PUSH] FIREBASE_CREDENTIALS_FILE не задан или файл не найден — FCM отключён")
        return False

    try:
        cred = credentials.Certificate(path)
        firebase_admin.initialize_app(cred)
        _fcm_initialized = True
        print("[PUSH] FCM инициализирован")
        return True
    except Exception as e:
        print(f"[PUSH] Ошибка инициализации FCM: {e}")
        return False


def send_push_notification(
    token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None,
):
    if not _init_fcm():
        return

    msg = messaging.Message(
        token=token,
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        data={k: str(v) for k, v in (data or {}).items()},
    )

    try:
        response = messaging.send(msg)
        print(f"[PUSH] FCM отправлен: {response}")
    except Exception as e:
        print(f"[PUSH] Ошибка отправки FCM: {e}")
