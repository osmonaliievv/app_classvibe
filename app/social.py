from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .database import get_db
from .auth import get_current_user
from .models import User, Follow, NotificationTypeEnum
from .schemas import UserShort, SimpleMessage
from .notifications import create_notification

router = APIRouter(prefix="/social", tags=["social"])


@router.post("/follow/{user_id}", response_model=SimpleMessage)
def follow_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.id == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя подписаться на себя")

    target = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    existing = (
        db.query(Follow)
        .filter(Follow.follower_id == current_user.id, Follow.following_id == user_id)
        .first()
    )
    if existing:
        return SimpleMessage(message="Вы уже подписаны")

    follow = Follow(follower_id=current_user.id, following_id=user_id)
    db.add(follow)

    current_user.following_count += 1
    target.followers_count += 1
    db.add(current_user)
    db.add(target)

    db.commit()

    # уведомление тому, на кого подписались
    create_notification(
        db=db,
        user_id=target.id,
        type=NotificationTypeEnum.new_follower,
        title="Новый подписчик",
        body=f"{current_user.first_name} {current_user.last_name} (@{current_user.username}) подписался на вас",
        data={"follower_id": current_user.id},
    )

    return SimpleMessage(message="Подписка оформлена")


@router.post("/unfollow/{user_id}", response_model=SimpleMessage)
def unfollow_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.id == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректная операция")

    target = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    existing = (
        db.query(Follow)
        .filter(Follow.follower_id == current_user.id, Follow.following_id == user_id)
        .first()
    )
    if not existing:
        return SimpleMessage(message="Вы не подписаны")

    db.delete(existing)

    if current_user.following_count > 0:
        current_user.following_count -= 1
    if target.followers_count > 0:
        target.followers_count -= 1
    db.add(current_user)
    db.add(target)

    db.commit()
    return SimpleMessage(message="Подписка удалена")


@router.get("/followers/{user_id}", response_model=List[UserShort])
def list_followers(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    follows = db.query(Follow).filter(Follow.following_id == user_id).all()
    users = [f.follower for f in follows]
    return users


@router.get("/following/{user_id}", response_model=List[UserShort])
def list_following(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    follows = db.query(Follow).filter(Follow.follower_id == user_id).all()
    users = [f.following for f in follows]
    return users
