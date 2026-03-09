from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from .database import get_db
from .auth import get_current_user
from .models import (
    User,
    Post,
    Comment,
    PostLike,
    CommentLike,
    SchoolEvent,
    SchoolAchievement,
    EventAttendance,
    EventStatusEnum,
    AchievementTargetEnum,
)
from .schemas import (
    SchoolLifeResponse,
    SchoolEventOut,
    SchoolEventCreateRequest,
    SchoolEventUpdateRequest,
    AchievementOut,
    AchievementCreateRequest,
    AchievementUpdateRequest,
    ActiveClassItem,
    PostOut,
)

router = APIRouter(prefix="/school-life", tags=["school-life"])


def _require_admin(user: User):
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Только администратор/модератор")


def _week_period_utc() -> Tuple[datetime, datetime]:
    now = datetime.utcnow()
    week_start = now - timedelta(days=now.weekday())
    week_start = datetime(week_start.year, week_start.month, week_start.day)
    week_end = week_start + timedelta(days=7)
    return week_start, week_end


def _best_posts_school(
    db: Session,
    school_name: str,
    hours: int = 48,
    limit: int = 5,
) -> List[Post]:
    """
    Лучшие посты школы за 24–48 часов.
    Возвращаем просто посты (без очков/мест).
    Скоринг внутренний (не показываем пользователю):
      score = like_count*2 + comment_count*3
    """
    since = datetime.utcnow() - timedelta(hours=hours)

    return (
        db.query(Post)
        .join(User, User.id == Post.user_id)
        .filter(
            User.school_name == school_name,
            Post.is_deleted.is_(False),
            Post.created_at >= since,
        )
        .order_by(desc((Post.like_count * 2) + (Post.comment_count * 3)), Post.created_at.desc())
        .limit(limit)
        .all()
    )


STATUS_LABELS = {
    "creative": "🎨 Креативный",
    "study": "📚 Учебный",
    "friendly": "🤝 Дружный",
    "creative_art": "🎭 Творческий",
    "sport": "⚽️ Спортивный",
}


def _pick_active_classes_week(
    db: Session,
    school_name: str,
    week_start: datetime,
    week_end: datetime,
    limit: int = 3,
) -> List[ActiveClassItem]:
    """
    Активные классы недели.
    ✅ Без мест, без очков, без сравнения.
    Просто выбираем несколько классов и назначаем "статус".
    """

    # Посты за неделю по классам
    posts_q = (
        db.query(User.grade.label("grade"), func.count(Post.id).label("cnt"))
        .join(Post, Post.user_id == User.id)
        .filter(
            User.school_name == school_name,
            User.grade.isnot(None),
            Post.is_deleted.is_(False),
            Post.created_at >= week_start,
            Post.created_at < week_end,
        )
        .group_by(User.grade)
        .all()
    )
    posts_map = {r.grade: int(r.cnt) for r in posts_q}

    # Комментарии за неделю по классам
    comments_q = (
        db.query(User.grade.label("grade"), func.count(Comment.id).label("cnt"))
        .join(Comment, Comment.user_id == User.id)
        .filter(
            User.school_name == school_name,
            User.grade.isnot(None),
            Comment.is_deleted.is_(False),
            Comment.created_at >= week_start,
            Comment.created_at < week_end,
        )
        .group_by(User.grade)
        .all()
    )
    comments_map = {r.grade: int(r.cnt) for r in comments_q}

    # Лайки, которые ученики поставили (как “дружность”)
    post_likes_q = (
        db.query(User.grade.label("grade"), func.count(PostLike.id).label("cnt"))
        .join(PostLike, PostLike.user_id == User.id)
        .join(Post, Post.id == PostLike.post_id)
        .filter(
            User.school_name == school_name,
            User.grade.isnot(None),
            Post.is_deleted.is_(False),
            PostLike.created_at >= week_start,
            PostLike.created_at < week_end,
        )
        .group_by(User.grade)
        .all()
    )
    comment_likes_q = (
        db.query(User.grade.label("grade"), func.count(CommentLike.id).label("cnt"))
        .join(CommentLike, CommentLike.user_id == User.id)
        .join(Comment, Comment.id == CommentLike.comment_id)
        .filter(
            User.school_name == school_name,
            User.grade.isnot(None),
            Comment.is_deleted.is_(False),
            CommentLike.created_at >= week_start,
            CommentLike.created_at < week_end,
        )
        .group_by(User.grade)
        .all()
    )

    likes_map: Dict[str, int] = {}
    for r in post_likes_q:
        likes_map[r.grade] = likes_map.get(r.grade, 0) + int(r.cnt)
    for r in comment_likes_q:
        likes_map[r.grade] = likes_map.get(r.grade, 0) + int(r.cnt)

    # Участие в событиях (если таблица будет заполняться)
    attendance_q = (
        db.query(User.grade.label("grade"), func.count(EventAttendance.id).label("cnt"))
        .join(EventAttendance, EventAttendance.user_id == User.id)
        .join(SchoolEvent, SchoolEvent.id == EventAttendance.event_id)
        .filter(
            User.school_name == school_name,
            User.grade.isnot(None),
            SchoolEvent.status == EventStatusEnum.published,
            EventAttendance.attended_at >= week_start,
            EventAttendance.attended_at < week_end,
        )
        .group_by(User.grade)
        .all()
    )
    attendance_map = {r.grade: int(r.cnt) for r in attendance_q}

    def pick_top(metric: Dict[str, int], exclude: set) -> Optional[str]:
        items = [(g, v) for g, v in metric.items() if g and g not in exclude and v > 0]
        if not items:
            return None
        items.sort(key=lambda x: x[1], reverse=True)
        return items[0][0]

    chosen: List[ActiveClassItem] = []
    used = set()

    # 1) 🎨 Креативный — больше постов
    g = pick_top(posts_map, used)
    if g:
        chosen.append(ActiveClassItem(grade=g, status="creative", label=STATUS_LABELS["creative"]))
        used.add(g)

    # 2) 📚 Учебный — больше комментов
    g = pick_top(comments_map, used)
    if g and len(chosen) < limit:
        chosen.append(ActiveClassItem(grade=g, status="study", label=STATUS_LABELS["study"]))
        used.add(g)

    # 3) 🤝 Дружный — больше лайков поставили
    g = pick_top(likes_map, used)
    if g and len(chosen) < limit:
        chosen.append(ActiveClassItem(grade=g, status="friendly", label=STATUS_LABELS["friendly"]))
        used.add(g)

    # 4) 🎭 Творческий — участие в событиях
    g = pick_top(attendance_map, used)
    if g and len(chosen) < limit:
        chosen.append(ActiveClassItem(grade=g, status="creative_art", label=STATUS_LABELS["creative_art"]))
        used.add(g)

    # 5) ⚽️ Спортивный — добираем по постам, если не хватает
    if len(chosen) < limit:
        remaining = [(gr, c) for gr, c in posts_map.items() if gr and gr not in used and c > 0]
        remaining.sort(key=lambda x: x[1], reverse=True)
        for gr, _ in remaining:
            if len(chosen) >= limit:
                break
            chosen.append(ActiveClassItem(grade=gr, status="sport", label=STATUS_LABELS["sport"]))
            used.add(gr)

    return chosen


@router.get("", response_model=SchoolLifeResponse)
def get_school_life(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    school_name: Optional[str] = None,
    events_limit: int = 3,
    best_posts_limit: int = 1,
    active_classes_limit: int = 3,
    achievements_limit: int = 5,
):
    """
    Один запрос для экрана "Жизнь школы" (как на дизайне).
    """
    target_school = school_name or current_user.school_name
    if not target_school:
        raise HTTPException(status_code=400, detail="Не указана школа (school_name в профиле)")

    now = datetime.utcnow()

    # События: ближайшие и актуальные
    events = (
        db.query(SchoolEvent)
        .filter(
            (SchoolEvent.school_name == target_school) | (SchoolEvent.school_name.is_(None)),
            SchoolEvent.status == EventStatusEnum.published,
            SchoolEvent.starts_at >= (now - timedelta(days=1)),
        )
        .order_by(SchoolEvent.starts_at.asc())
        .limit(events_limit)
        .all()
    )

    # Лучшие посты школы: за 48 часов
    best_posts = _best_posts_school(db, target_school, hours=48, limit=best_posts_limit)

    week_start, week_end = _week_period_utc()

    # Активные классы недели (без мест/очков)
    active_classes = _pick_active_classes_week(
        db, target_school, week_start, week_end, limit=active_classes_limit
    )

    # Достижения: последние
    achievements = (
        db.query(SchoolAchievement)
        .filter(
            (SchoolAchievement.school_name == target_school) | (SchoolAchievement.school_name.is_(None)),
        )
        .order_by(desc(func.coalesce(SchoolAchievement.achieved_at, SchoolAchievement.created_at)))
        .limit(achievements_limit)
        .all()
    )

    return SchoolLifeResponse(
        school_name=target_school,
        events=events,
        best_posts=best_posts,
        active_classes=active_classes,
        achievements=achievements,
        week_start=week_start,
        week_end=week_end,
    )


# -------- Events (admin) --------

@router.get("/events", response_model=List[SchoolEventOut])
def list_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    school_name: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    include_past: bool = False,
):
    target_school = school_name or current_user.school_name
    if not target_school:
        raise HTTPException(status_code=400, detail="Не указана школа")

    q = (
        db.query(SchoolEvent)
        .filter(
            (SchoolEvent.school_name == target_school) | (SchoolEvent.school_name.is_(None)),
            SchoolEvent.status == EventStatusEnum.published,
        )
    )
    if not include_past:
        q = q.filter(SchoolEvent.starts_at >= (datetime.utcnow() - timedelta(days=1)))

    return q.order_by(SchoolEvent.starts_at.asc()).offset(offset).limit(limit).all()


@router.post("/events", response_model=SchoolEventOut, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: SchoolEventCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)

    ev = SchoolEvent(
        school_name=payload.school_name or current_user.school_name,
        title=payload.title,
        cover_url=payload.cover_url,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        location=payload.location,
        description=payload.description,
        status=EventStatusEnum(payload.status or "published"),
        created_by_id=current_user.id,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


@router.patch("/events/{event_id}", response_model=SchoolEventOut)
def update_event(
    event_id: int,
    payload: SchoolEventUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)

    ev = db.query(SchoolEvent).filter(SchoolEvent.id == event_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Событие не найдено")

    for field, value in payload.dict(exclude_unset=True).items():
        if field == "status" and value is not None:
            setattr(ev, field, EventStatusEnum(value))
        else:
            setattr(ev, field, value)

    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)

    ev = db.query(SchoolEvent).filter(SchoolEvent.id == event_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Событие не найдено")

    db.delete(ev)
    db.commit()
    return


# -------- Achievements (admin) --------

@router.get("/achievements", response_model=List[AchievementOut])
def list_achievements(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    school_name: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    target_school = school_name or current_user.school_name
    if not target_school:
        raise HTTPException(status_code=400, detail="Не указана школа")

    return (
        db.query(SchoolAchievement)
        .filter(
            (SchoolAchievement.school_name == target_school) | (SchoolAchievement.school_name.is_(None)),
        )
        .order_by(desc(func.coalesce(SchoolAchievement.achieved_at, SchoolAchievement.created_at)))
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.post("/achievements", response_model=AchievementOut, status_code=status.HTTP_201_CREATED)
def create_achievement(
    payload: AchievementCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)

    if payload.target == "grade" and not payload.grade:
        raise HTTPException(status_code=400, detail="Для target=grade нужно поле grade")

    ach = SchoolAchievement(
        school_name=payload.school_name or current_user.school_name,
        target=AchievementTargetEnum(payload.target),
        grade=payload.grade,
        title=payload.title,
        description=payload.description,
        cover_url=payload.cover_url,
        achieved_at=payload.achieved_at,
        created_by_id=current_user.id,
    )
    db.add(ach)
    db.commit()
    db.refresh(ach)
    return ach


@router.patch("/achievements/{achievement_id}", response_model=AchievementOut)
def update_achievement(
    achievement_id: int,
    payload: AchievementUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)

    ach = db.query(SchoolAchievement).filter(SchoolAchievement.id == achievement_id).first()
    if not ach:
        raise HTTPException(status_code=404, detail="Достижение не найдено")

    data = payload.dict(exclude_unset=True)

    if "target" in data and data["target"] is not None:
        data["target"] = AchievementTargetEnum(data["target"])

    new_target = data.get("target", ach.target)
    new_grade = data.get("grade", ach.grade)
    if new_target == AchievementTargetEnum.grade and not new_grade:
        raise HTTPException(status_code=400, detail="Для target=grade нужно поле grade")

    for k, v in data.items():
        setattr(ach, k, v)

    db.add(ach)
    db.commit()
    db.refresh(ach)
    return ach


@router.delete("/achievements/{achievement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_achievement(
    achievement_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)

    ach = db.query(SchoolAchievement).filter(SchoolAchievement.id == achievement_id).first()
    if not ach:
        raise HTTPException(status_code=404, detail="Достижение не найдено")

    db.delete(ach)
    db.commit()
    return