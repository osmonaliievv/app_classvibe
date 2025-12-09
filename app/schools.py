# app/schools.py

from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from .auth import get_current_user
from .models import (
    User,
    Post,
    Comment,
    PostLike,
    CommentLike,
    NotificationTypeEnum,
)
from .schemas import ClassRatingResponse, ClassRatingItem
from .notifications import create_notification

router = APIRouter(
    prefix="/schools",
    tags=["schools"],
)

# --- Константы для расчёта баллов ---

POST_POINTS = 5             # за каждый созданный пост
COMMENT_POINTS = 2          # за каждый комментарий
POST_LIKE_POINTS = 1        # за каждый лайк поста (автору поста)
COMMENT_LIKE_POINTS = 1     # за каждый лайк комментария (автору комментария)

MAX_PLACES = 9  # показываем только 1–9 место (как на дизайне)


def _get_current_week_period() -> (datetime, datetime):
    """
    Возвращает (week_start, week_end) для текущей недели.
    Неделя: с понедельника 00:00 (UTC) до следующего понедельника 00:00.
    """
    now = datetime.utcnow()
    week_start = now - timedelta(days=now.weekday())
    week_start = datetime(week_start.year, week_start.month, week_start.day)
    week_end = week_start + timedelta(days=7)
    return week_start, week_end


@router.get("/class-rating", response_model=ClassRatingResponse)
def get_class_rating(
    school_name: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Рейтинг классов внутри одной школы.

    Начисление очков:
      +5 очков за каждый пост (создан на этой неделе)
      +2 очка за каждый комментарий (создан на этой неделе)
      +1 очко за каждый лайк поста (поставлен на этой неделе)
      +1 очко за каждый лайк комментария (поставлен на этой неделе)

    Период: текущая неделя (понедельник–понедельник).
    В ответе — только ТОП-9 классов.
    При равенстве очков внутри группы порядок случайный.
    """

    target_school = school_name or current_user.school_name
    if not target_school:
        raise HTTPException(
            status_code=400,
            detail=(
                "Не указана школа. Либо передайте параметр school_name, "
                "либо заполните школу в своём профиле."
            ),
        )

    week_start, week_end = _get_current_week_period()

    # key: grade, value: {"points": int, "students": set(user_id)}
    class_stats: Dict[str, Dict[str, object]] = {}

    def add_points(grade: Optional[str], user_id: int, pts: int):
        grade_key = grade or "Без класса"
        if grade_key not in class_stats:
            class_stats[grade_key] = {
                "points": 0,
                "students": set(),
            }
        class_stats[grade_key]["points"] += pts
        class_stats[grade_key]["students"].add(user_id)

    # --- Посты этой школы за неделю ---
    posts = (
        db.query(Post.id, Post.user_id, Post.created_at, User.grade)
        .join(User, User.id == Post.user_id)
        .filter(
            User.school_name == target_school,
            Post.is_deleted.is_(False),
            Post.created_at >= week_start,
            Post.created_at < week_end,
        )
        .all()
    )
    for post_id, user_id, created_at, grade in posts:
        add_points(grade, user_id, POST_POINTS)

    # --- Комментарии ---
    comments = (
        db.query(Comment.id, Comment.user_id, Comment.created_at, User.grade)
        .join(User, User.id == Comment.user_id)
        .filter(
            User.school_name == target_school,
            Comment.is_deleted.is_(False),
            Comment.created_at >= week_start,
            Comment.created_at < week_end,
        )
        .all()
    )
    for comment_id, user_id, created_at, grade in comments:
        add_points(grade, user_id, COMMENT_POINTS)

    # --- Лайки постов ---
    post_likes = (
        db.query(PostLike.id, Post.user_id, PostLike.created_at, User.grade)
        .join(Post, PostLike.post_id == Post.id)
        .join(User, User.id == Post.user_id)
        .filter(
            User.school_name == target_school,
            Post.is_deleted.is_(False),
            PostLike.created_at >= week_start,
            PostLike.created_at < week_end,
        )
        .all()
    )
    for like_id, post_author_id, created_at, grade in post_likes:
        add_points(grade, post_author_id, POST_LIKE_POINTS)

    # --- Лайки комментариев ---
    comment_likes = (
        db.query(CommentLike.id, Comment.user_id, CommentLike.created_at, User.grade)
        .join(Comment, CommentLike.comment_id == Comment.id)
        .join(User, User.id == Comment.user_id)
        .filter(
            User.school_name == target_school,
            Comment.is_deleted.is_(False),
            CommentLike.created_at >= week_start,
            CommentLike.created_at < week_end,
        )
        .all()
    )
    for like_id, comment_author_id, created_at, grade in comment_likes:
        add_points(grade, comment_author_id, COMMENT_LIKE_POINTS)

    if not class_stats:
        # за неделю не было активности
        return ClassRatingResponse(
            school_name=target_school,
            my_class=current_user.grade,
            my_class_place=None,
            my_class_points=None,
            items=[],
            period_start=week_start,
            period_end=week_end,
        )

    # сортировка: по очкам (DESC), при равенстве — случайный порядок
    sorted_classes: List[Tuple[str, Dict[str, object]]] = sorted(
        class_stats.items(),
        key=lambda kv: (-int(kv[1]["points"]), random.random()),
    )

    my_grade = current_user.grade
    my_place: Optional[int] = None
    my_points: Optional[int] = None

    items: List[ClassRatingItem] = []

    for idx, (grade, data) in enumerate(sorted_classes, start=1):
        points = int(data["points"])
        students_count = len(data["students"])

        items.append(
            ClassRatingItem(
                place=idx,
                grade=grade,
                points=points,
                students_count=students_count,
            )
        )

        if my_grade is not None and grade == my_grade:
            my_place = idx
            my_points = points

    # только 1–9 места
    items = items[:MAX_PLACES]

    # уведомление, если мой класс попал в топ-9
    if my_grade and my_place is not None and my_place <= MAX_PLACES:
        create_notification(
            db=db,
            user_id=current_user.id,
            type=NotificationTypeEnum.class_rating,
            title="Рейтинг классов",
            body=(
                f"Ваш класс сейчас на {my_place}-м месте "
                f"в рейтинге школы «{target_school}»."
            ),
            data={
                "school_name": target_school,
                "place": my_place,
                "points": my_points,
                "period_start": week_start.isoformat(),
                "period_end": week_end.isoformat(),
            },
        )

    return ClassRatingResponse(
        school_name=target_school,
        my_class=my_grade,
        my_class_place=my_place,
        my_class_points=my_points,
        items=items,
        period_start=week_start,
        period_end=week_end,
    )
