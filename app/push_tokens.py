# app/push_tokens.py
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .auth import get_current_user
from .database import get_db
from . import models, schemas

router = APIRouter(prefix="/push", tags=["push"])


@router.post("/register", response_model=schemas.PushTokenOut)
def register_push_token(
    payload: schemas.PushTokenRegisterRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # удаляем старые записи с этим токеном
    (
        db.query(models.PushToken)
        .filter(models.PushToken.token == payload.token)
        .delete()
    )

    token = models.PushToken(
        user_id=current_user.id,
        platform=payload.platform,
        token=payload.token,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


@router.delete("/unregister", response_model=schemas.SimpleMessage)
def unregister_push_token(
    token: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    (
        db.query(models.PushToken)
        .filter(
            models.PushToken.token == token,
            models.PushToken.user_id == current_user.id,
        )
        .delete()
    )
    db.commit()
    return schemas.SimpleMessage(message="Токен удалён")


@router.get("/list", response_model=List[schemas.PushTokenOut])
def list_my_push_tokens(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tokens = (
        db.query(models.PushToken)
        .filter(models.PushToken.user_id == current_user.id)
        .order_by(models.PushToken.created_at.desc())
        .all()
    )
    return tokens
