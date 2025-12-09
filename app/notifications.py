# app/notifications.py
from typing import List, Optional, Dict

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from .database import get_db
from .auth import get_current_user
from . import models, schemas
from .push import send_push_notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


def create_notification(
    db: Session,
    user_id: int,
    type: models.NotificationTypeEnum,
    title: str,
    body: Optional[str] = None,
    data: Optional[Dict] = None,
):
    """
    Утилита для создания уведомления (вызывается из других роутеров) + FCM.
    """
    notif = models.Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        data=data or {},
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)

    # FCM push для всех устройств пользователя
    tokens = (
        db.query(models.PushToken)
        .filter(models.PushToken.user_id == user_id)
        .all()
    )
    for t in tokens:
        send_push_notification(
            token=t.token,
            title=title,
            body=body or "",
            data={(k): str(v) for k, v in (data or {}).items()},
        )

    return notif


@router.get("/", response_model=List[schemas.NotificationOut])
def list_notifications(
    only_unread: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id
    )

    if only_unread:
        q = q.filter(models.Notification.is_read == False)

    notifications = (
        q.order_by(models.Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return notifications


@router.post("/{notification_id}/read", response_model=schemas.NotificationOut)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    notif = (
        db.query(models.Notification)
        .filter(
            models.Notification.id == notification_id,
            models.Notification.user_id == current_user.id,
        )
        .first()
    )
    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Уведомление не найдено",
        )

    notif.is_read = True
    db.commit()
    db.refresh(notif)
    return notif


@router.post("/read-all", response_model=schemas.SimpleMessage)
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == current_user.id,
            models.Notification.is_read == False,
        )
        .update({"is_read": True})
    )
    db.commit()
    return schemas.SimpleMessage(message="Все уведомления отмечены как прочитанные")
