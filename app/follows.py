from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .auth import get_current_user
from .models import User, Follow, NotificationTypeEnum
from .notifications import create_notification

router = APIRouter(prefix="/follows", tags=["Подписки"])


@router.post("/{user_id}/toggle")
async def toggle_follow(
        user_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя подписаться на самого себя"
        )

    # Проверяем существование целевого пользователя
    target_user_query = await db.execute(select(User).where(User.id == user_id))
    target_user = target_user_query.scalar_one_or_none()

    if not target_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Ищем существующую подписку
    follow_query = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id
        )
    )
    follow = follow_query.scalar_one_or_none()

    if follow:
        # --- ОТПИСКА ---
        await db.delete(follow)

        # Атомарно уменьшаем счетчики
        await db.execute(
            update(User).where(User.id == current_user.id).values(following_count=User.following_count - 1)
        )
        await db.execute(
            update(User).where(User.id == user_id).values(followers_count=User.followers_count - 1)
        )

        res_status = "unfollowed"
    else:
        # --- ПОДПИСКА ---
        new_follow = Follow(follower_id=current_user.id, following_id=user_id)
        db.add(new_follow)

        # Атомарно увеличиваем счетчики
        await db.execute(
            update(User).where(User.id == current_user.id).values(following_count=User.following_count + 1)
        )
        await db.execute(
            update(User).where(User.id == user_id).values(followers_count=User.followers_count + 1)
        )

        # Создаем уведомление (асинхронно)
        await create_notification(
            db,
            user_id=user_id,
            type=NotificationTypeEnum.new_follower,
            title="Новый подписчик",
            body=f"@{current_user.username} подписался на вас",
            data={"follower_id": current_user.id}
        )

        res_status = "followed"

    # Фиксируем все изменения одной транзакцией
    await db.commit()

    return {"status": res_status}


@router.get("/{user_id}/followers", response_model=list)
async def get_followers(user_id: int, db: AsyncSession = Depends(get_db)):
    """Список тех, кто подписан на пользователя."""
    query = select(Follow).where(Follow.following_id == user_id)
    result = await db.execute(query)
    # Здесь можно добавить join с моделью User, чтобы вернуть полные данные
    return result.scalars().all()
