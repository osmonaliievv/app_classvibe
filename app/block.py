from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .database import get_db
from .auth import get_current_user
from .models import User, Block
from .schemas import SimpleMessage

router = APIRouter(prefix="/block", tags=["block"])


@router.post("/{user_id}", response_model=SimpleMessage)
def block_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя заблокировать самого себя")

    target = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not target:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    existing = (
        db.query(Block)
        .filter(Block.blocker_id == current_user.id, Block.blocked_id == user_id)
        .first()
    )

    if existing:
        return SimpleMessage(message="Пользователь уже заблокирован")

    block = Block(blocker_id=current_user.id, blocked_id=user_id)
    db.add(block)
    db.commit()

    return SimpleMessage(message="Пользователь заблокирован")


@router.post("/unblock/{user_id}", response_model=SimpleMessage)
def unblock_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    block = (
        db.query(Block)
        .filter(Block.blocker_id == current_user.id, Block.blocked_id == user_id)
        .first()
    )

    if not block:
        return SimpleMessage(message="Пользователь не был заблокирован")

    db.delete(block)
    db.commit()

    return SimpleMessage(message="Пользователь разблокирован")


@router.get("/list", response_model=list[int])
def get_block_list(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    blocks = (
        db.query(Block)
        .filter(Block.blocker_id == current_user.id)
        .all()
    )
    return [b.blocked_id for b in blocks]