import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

# JWT / app
SECRET_KEY = os.getenv("SECRET_KEY") or os.getenv("JWT_SECRET", "dev_secret_change_me")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRES_MINUTES = int(
    os.getenv("ACCESS_TOKEN_EXPIRES_MINUTES") or os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
)

# Firebase FCM (если push оставляете)
FCM_CREDENTIALS_PATH = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "")

# Twilio Verify
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_VERIFY_SERVICE_SID = os.getenv("TWILIO_VERIFY_SERVICE_SID", "")

def get_access_token_expires_delta() -> timedelta:
    return timedelta(minutes=ACCESS_TOKEN_EXPIRES_MINUTES)