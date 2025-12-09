# app/reports.py

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, constr
from sqlalchemy.orm import Session

from .database import get_db
from .auth import get_current_user
from . import models

router = APIRouter(
    prefix="/reports",
    tags=["reports"],
)


class CreateReportRequest(BaseModel):
    target_type: models.ReportTargetTypeEnum  # post / comment / user / message
    target_id: int
    reason: models.ReportReasonEnum          # nudity, illegal, bullying...
    description: constr(max_length=1000) | None = None


class ReportItem(BaseModel):
    id: int
    target_type: models.ReportTargetTypeEnum
    reason: models.ReportReasonEnum
    description: str | None
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_report(
    payload: CreateReportRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Создать жалобу на контент.
    target_type + target_id:
      - post    -> id поста
      - comment -> id комментария
      - user    -> id пользователя
      - message -> id сообщения
    """
    post_id = None
    comment_id = None
    target_user_id = None
    message_id = None

    if payload.target_type == models.ReportTargetTypeEnum.post:
        post = db.query(models.Post).filter(models.Post.id == payload.target_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Пост не найден")
        post_id = post.id

    elif payload.target_type == models.ReportTargetTypeEnum.comment:
        comment = db.query(models.Comment).filter(models.Comment.id == payload.target_id).first()
        if not comment:
            raise HTTPException(status_code=404, detail="Комментарий не найден")
        comment_id = comment.id

    elif payload.target_type == models.ReportTargetTypeEnum.user:
        user = db.query(models.User).filter(models.User.id == payload.target_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        target_user_id = user.id

    elif payload.target_type == models.ReportTargetTypeEnum.message:
        message = db.query(models.Message).filter(models.Message.id == payload.target_id).first()
        if not message:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")
        message_id = message.id
    else:
        raise HTTPException(status_code=400, detail="Неверный тип объекта для жалобы")

    report = models.ContentReport(
        reporter_id=current_user.id,
        target_type=payload.target_type,
        post_id=post_id,
        comment_id=comment_id,
        target_user_id=target_user_id,
        message_id=message_id,
        reason=payload.reason,
        description=payload.description,
        created_at=datetime.utcnow(),
    )

    db.add(report)
    db.commit()
    db.refresh(report)

    return {"detail": "Жалоба отправлена. Спасибо за помощь в модерации."}


@router.get("/my", response_model=List[ReportItem])
def list_my_reports(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Жалобы, которые отправил текущий пользователь.
    """
    reports = (
        db.query(models.ContentReport)
        .filter(models.ContentReport.reporter_id == current_user.id)
        .order_by(models.ContentReport.created_at.desc())
        .all()
    )
    return reports


@router.get("/", response_model=List[ReportItem])
def list_all_reports(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Все жалобы (для админа).
    Пока без проверки роли — ограничьте доступ только токенами админов.
    """
    reports = (
        db.query(models.ContentReport)
        .order_by(models.ContentReport.created_at.desc())
        .all()
    )
    return reports
