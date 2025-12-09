# app/profile.py
from pathlib import Path
import os

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.orm import Session

from . import models, schemas
from .database import get_db
from .auth import get_current_user

router = APIRouter(prefix="/profile", tags=["profile"])

MEDIA_ROOT = Path("media")
AVATARS_DIR = MEDIA_ROOT / "avatars"
AVATARS_DIR.mkdir(parents=True, exist_ok=True)


@router.get("/me", response_model=schemas.UserBase)
def get_my_profile(
    current_user: models.User = Depends(get_current_user),
):
    """
    Мой профиль по токену.
    """
    return current_user


@router.patch("/me", response_model=schemas.UserBase)
def update_my_profile(
    data: schemas.ProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Обновление профиля:
    - first_name, last_name
    - school_name, grade
    - status, city, bio
    - role (ученик / учитель / студент) — можно менять
    """

    if data.first_name is not None:
        current_user.first_name = data.first_name

    if data.last_name is not None:
        current_user.last_name = data.last_name

    if data.school_name is not None:
        current_user.school_name = data.school_name

    if data.grade is not None:
        current_user.grade = data.grade

    if data.status is not None:
        current_user.status = data.status

    if data.city is not None:
        current_user.city = data.city

    if data.bio is not None:
        current_user.bio = data.bio

    # смена роли (ученик / учитель / студент)
    if data.role is not None:
        current_user.role = data.role

    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/change-username", response_model=schemas.UserBase)
def change_username(
    data: schemas.ChangeUsernameRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Смена username.
    Ограничения по символам проверяются в Pydantic-схеме:
    - только латинские буквы
    - цифры
    - "_"
    """

    existing = (
        db.query(models.User)
        .filter(
            models.User.username == data.new_username,
            models.User.id != current_user.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Это имя пользователя уже занято",
        )

    current_user.username = data.new_username
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/avatar", response_model=schemas.UserBase)
async def upload_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Загрузка аватара пользователя.
    Сохраняем файл в /media/avatars и обновляем avatar_url.
    """

    if not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Можно загружать только изображения",
        )

    ext = os.path.splitext(file.filename)[1] or ".png"
    filename = f"avatar_{current_user.id}{ext}"
    filepath = AVATARS_DIR / filename

    with open(filepath, "wb") as out_file:
        out_file.write(await file.read())

    current_user.avatar_url = f"/media/avatars/{filename}"
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/by-username/{username}", response_model=schemas.UserBase)
def get_profile_by_username(
    username: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Профиль по username (для просмотра чужих профилей).
    """

    user = (
        db.query(models.User)
        .filter(models.User.username == username, models.User.is_active == True)
        .first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        )
    return user
