from twilio.rest import Client
from fastapi import HTTPException, status

from .config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_VERIFY_SERVICE_SID,
)


def _get_client() -> Client:
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_VERIFY_SERVICE_SID:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Twilio Verify не настроен на сервере",
        )
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def send_verification_code(phone: str):
    client = _get_client()
    try:
        verification = (
            client.verify.v2.services(TWILIO_VERIFY_SERVICE_SID)
            .verifications
            .create(to=phone, channel="sms")
        )
        return verification
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Не удалось отправить SMS-код: {str(e)}",
        )


def check_verification_code(phone: str, code: str):
    client = _get_client()
    try:
        verification_check = (
            client.verify.v2.services(TWILIO_VERIFY_SERVICE_SID)
            .verification_checks
            .create(to=phone, code=code)
        )
        return verification_check
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Не удалось проверить код: {str(e)}",
        )