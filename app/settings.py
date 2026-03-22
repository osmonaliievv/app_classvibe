# app/settings.py

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, constr
from sqlalchemy.orm import Session

from .database import get_db
from .models import (
    User,
    PushToken,
    SupportRequest,
    SupportRequestStatusEnum,
)
from .auth import get_current_user, verify_password, get_password_hash

router = APIRouter(
    prefix="/settings",
    tags=["settings"],
)


# ---------- Схемы запросов / ответов ----------

class ChangePasswordRequest(BaseModel):
    old_password: constr(min_length=6, max_length=128)
    new_password: constr(min_length=6, max_length=128)


class UpdatePhoneRequest(BaseModel):
    phone: constr(min_length=5, max_length=32)


class UpdateEmailRequest(BaseModel):
    email: EmailStr


class NotificationToggleRequest(BaseModel):
    enabled: bool


class SettingsInfoResponse(BaseModel):
    phone: str | None
    email: EmailStr | None
    notifications_enabled: bool


class AboutAppResponse(BaseModel):
    name: str
    version: str
    description: str
    website: str | None = None


class TermsResponse(BaseModel):
    title: str
    content: str


class ReportProblemRequest(BaseModel):
    subject: str | None = None
    message: constr(min_length=10, max_length=2000)
    app_version: str | None = None
    device_info: str | None = None


class SupportRequestItem(BaseModel):
    id: int
    subject: str | None
    message: str
    app_version: str | None
    device_info: str | None
    status: SupportRequestStatusEnum
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Вспомогательные функции ----------

def _get_notifications_enabled(user: User) -> bool:
    # ✅ Берём значение прямо из поля пользователя
    return bool(getattr(user, "notifications_enabled", True))


# ---------- Основные настройки ----------

@router.get("/", response_model=SettingsInfoResponse)
def get_settings(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    return SettingsInfoResponse(
        phone=current_user.phone,
        email=current_user.email,
        notifications_enabled=_get_notifications_enabled(current_user),
    )


@router.post("/change-password")
def change_password(
        payload: ChangePasswordRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный текущий пароль.",
        )

    if payload.old_password == payload.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый пароль не должен совпадать с текущим.",
        )

    current_user.password_hash = get_password_hash(payload.new_password)
    db.add(current_user)
    db.commit()

    return {"detail": "Пароль успешно изменён."}


@router.patch("/phone")
def update_phone(
        payload: UpdatePhoneRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    new_phone = payload.phone.strip()

    if current_user.phone == new_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый номер телефона совпадает с текущим.",
        )

    existing = (
        db.query(User)
        .filter(
            User.phone == new_phone,
            User.id != current_user.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот номер телефона уже используется другим аккаунтом.",
        )

    current_user.phone = new_phone
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    return {"detail": "Номер телефона успешно обновлён.", "phone": current_user.phone}


@router.patch("/email")
def update_email(
        payload: UpdateEmailRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    new_email = payload.email.strip().lower()

    if current_user.email and current_user.email.lower() == new_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый email совпадает с текущим.",
        )

    existing = (
        db.query(User)
        .filter(
            User.email == new_email,
            User.id != current_user.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот email уже используется другим аккаунтом.",
        )

    current_user.email = new_email
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    return {"detail": "Email успешно обновлён.", "email": current_user.email}


@router.patch("/notifications")
def toggle_notifications(
        payload: NotificationToggleRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    # ✅ Сохраняем в поле пользователя
    current_user.notifications_enabled = payload.enabled
    db.add(current_user)

    # ✅ Также обновляем push токены если есть
    db.query(PushToken).filter(
        PushToken.user_id == current_user.id,
    ).update(
        {"is_active": payload.enabled},
        synchronize_session=False,
    )

    db.commit()
    db.refresh(current_user)

    return {
        "detail": "Настройки уведомлений обновлены.",
        "notifications_enabled": current_user.notifications_enabled,
    }


# ---------- О приложении и условия ----------

@router.get("/about", response_model=AboutAppResponse)
def get_about_app():
    return AboutAppResponse(
        name="ClassVibe",
        version="1.0.0",
        description=(
            "ClassVibe — социальная платформа для школьников, студентов и учителей. "
            "Помогает общаться, делиться новостями, вести чаты классов и школ, "
            "участвовать в мероприятиях и развивать школьное комьюнити."
        ),
        website=None,
    )


@router.get("/terms", response_model=TermsResponse)
def get_terms():
    return TermsResponse(
        title="Условия использования ClassVibe",
        content=(
            "Используя приложение ClassVibe, вы соглашаетесь соблюдать правила сообщества, "
            "уважать других пользователей и не публиковать запрещённый контент. "
            "Администрация оставляет за собой право ограничивать доступ к сервису при нарушениях. "
            "Это базовый текст для MVP, полноценные юридические условия можно добавить позже."
        ),
    )


# ---------- Сообщить о проблеме ----------

@router.post("/report-problem")
def report_problem(
        payload: ReportProblemRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    support = SupportRequest(
        user_id=current_user.id,
        subject=payload.subject,
        message=payload.message,
        app_version=payload.app_version,
        device_info=payload.device_info,
        status=SupportRequestStatusEnum.new,
    )

    db.add(support)
    db.commit()
    db.refresh(support)

    return {
        "detail": "Сообщение о проблеме отправлено. Спасибо!",
        "id": support.id,
        "status": support.status.value,
    }


@router.get("/my-reports", response_model=list[SupportRequestItem])
def get_my_reports(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    items = (
        db.query(SupportRequest)
        .filter(SupportRequest.user_id == current_user.id)
        .order_by(SupportRequest.created_at.desc())
        .all()
    )
    return items


@router.get("/support-requests", response_model=list[SupportRequestItem])
def get_all_support_requests(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    items = (
        db.query(SupportRequest)
        .order_by(SupportRequest.created_at.desc())
        .all()
    )
    return items