from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .auth import get_current_user
from .database import get_db
from .models import (
    AchievementTargetEnum,
    Chat,
    Comment,
    ContentReport,
    EventStatusEnum,
    Message,
    Post,
    PostLike,
    SchoolAchievement,
    SchoolEvent,
    User,
)
from .schemas import (
    AchievementCreateRequest,
    AchievementOut,
    AchievementUpdateRequest,
    AdminDashboardOut,
    AdminReportActionRequest,
    AdminReportItem,
    AdminReportListResponse,
    AdminUserListResponse,
    AdminUserShort,
    PostOut,
    SchoolEventCreateRequest,
    SchoolEventOut,
    SchoolEventUpdateRequest,
    SimpleMessage,
)

router = APIRouter(prefix="/admin", tags=["admin"])


# =========================================================
# Helper: only admins
# =========================================================
def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешён только администраторам",
        )
    return current_user


# =========================================================
# Dashboard
# =========================================================
@router.get("/dashboard", response_model=AdminDashboardOut)
def admin_dashboard(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    users_total = db.query(User).count()
    users_active = db.query(User).filter(User.is_active.is_(True)).count()
    posts_total = db.query(Post).filter(Post.is_deleted.is_(False)).count()
    comments_total = db.query(Comment).filter(Comment.is_deleted.is_(False)).count()
    messages_total = db.query(Message).count()
    likes_count = db.query(PostLike).count()
    active_chats = db.query(Chat).filter(Chat.is_deleted.is_(False)).count()
    reports_open = db.query(ContentReport).filter(
        ContentReport.is_processed.is_(False)
    ).count()

    return AdminDashboardOut(
        users_total=users_total,
        users_active=users_active,
        posts_total=posts_total,
        comments_total=comments_total,
        messages_total=messages_total,
        reports_open=reports_open,
        likes_count=likes_count,
        active_chats=active_chats,
    )


# =========================================================
# Users
# =========================================================
@router.get("/users", response_model=AdminUserListResponse)
def admin_list_users(
    q: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    query = db.query(User)

    if q:
        pattern = f"%{q}%"
        query = query.filter(
            or_(
                User.username.ilike(pattern),
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
                User.phone.ilike(pattern),
                User.email.ilike(pattern),
            )
        )

    if is_active is not None:
        query = query.filter(User.is_active.is_(is_active))

    users: List[User] = (
        query.order_by(User.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = [AdminUserShort.model_validate(u) for u in users]
    return AdminUserListResponse(items=items)


@router.post("/users/{user_id}/ban", response_model=SimpleMessage)
def admin_ban_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    user.is_active = False
    db.commit()
    return SimpleMessage(message=f"Пользователь id={user_id} заблокирован")


@router.post("/users/{user_id}/unban", response_model=SimpleMessage)
def admin_unban_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    user.is_active = True
    db.commit()
    return SimpleMessage(message=f"Пользователь id={user_id} разблокирован")


@router.delete("/users/{user_id}", response_model=SimpleMessage)
def admin_delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    db.delete(user)
    db.commit()
    return SimpleMessage(message=f"Пользователь id={user_id} полностью удалён из базы")


# =========================================================
# Reports
# =========================================================
@router.get("/reports", response_model=AdminReportListResponse)
def admin_list_reports(
    only_open: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    query = db.query(ContentReport)

    if only_open:
        query = query.filter(ContentReport.is_processed.is_(False))

    reports: List[ContentReport] = query.order_by(ContentReport.created_at.desc()).all()
    items = [AdminReportItem.model_validate(r) for r in reports]
    return AdminReportListResponse(items=items)


@router.post("/reports/{report_id}/action", response_model=SimpleMessage)
def admin_process_report(
    report_id: int,
    data: AdminReportActionRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    report = db.query(ContentReport).filter(ContentReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Жалоба не найдена")

    action = data.action

    if action == "delete_post":
        if not report.post_id:
            raise HTTPException(status_code=400, detail="У жалобы нет связанного поста")
        post = db.query(Post).filter(Post.id == report.post_id).first()
        if post:
            post.is_deleted = True

    elif action == "delete_comment":
        if not report.comment_id:
            raise HTTPException(
                status_code=400,
                detail="У жалобы нет связанного комментария",
            )
        comment = db.query(Comment).filter(Comment.id == report.comment_id).first()
        if comment:
            comment.is_deleted = True

    elif action == "delete_message":
        if not report.message_id:
            raise HTTPException(
                status_code=400,
                detail="У жалобы нет связанного сообщения",
            )
        message = db.query(Message).filter(Message.id == report.message_id).first()
        if message:
            message.is_deleted = True

    elif action == "ban_user":
        target_user_id = data.ban_user_id or report.target_user_id
        if not target_user_id:
            raise HTTPException(
                status_code=400,
                detail="Не указан пользователь для блокировки",
            )

        user = db.query(User).filter(User.id == target_user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        user.is_active = False

    report.is_processed = True
    db.commit()

    return SimpleMessage(
        message=f"Жалоба id={report_id} обработана действием '{action}'"
    )


# =========================================================
# Posts moderation
# =========================================================
@router.get("/posts", response_model=List[PostOut])
def admin_list_posts(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    posts = (
        db.query(Post)
        .order_by(Post.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return posts


@router.delete("/posts/{post_id}", response_model=SimpleMessage)
def admin_delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")

    post.is_deleted = True
    db.commit()
    return SimpleMessage(message=f"Пост id={post_id} удалён модератором")


# =========================================================
# Admin School Events
# =========================================================
@router.get("/school-events", response_model=List[SchoolEventOut])
def admin_list_school_events(
    school_name: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    q = db.query(SchoolEvent)

    if school_name:
        q = q.filter(SchoolEvent.school_name == school_name)

    if status_filter:
        try:
            q = q.filter(SchoolEvent.status == EventStatusEnum(status_filter))
        except ValueError:
            raise HTTPException(status_code=400, detail="Некорректный status_filter")

    return (
        q.order_by(SchoolEvent.starts_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/school-events/{event_id}", response_model=SchoolEventOut)
def admin_get_school_event(
    event_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    event = db.query(SchoolEvent).filter(SchoolEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Событие не найдено")
    return event


@router.post(
    "/school-events",
    response_model=SchoolEventOut,
    status_code=status.HTTP_201_CREATED,
)
def admin_create_school_event(
    payload: SchoolEventCreateRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    event = SchoolEvent(
        school_name=payload.school_name,
        title=payload.title,
        cover_url=payload.cover_url,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        location=payload.location,
        description=payload.description,
        status=EventStatusEnum(payload.status or "published"),
        created_by_id=current_admin.id,
    )

    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.patch("/school-events/{event_id}", response_model=SchoolEventOut)
@router.put("/school-events/{event_id}", response_model=SchoolEventOut)
def admin_update_school_event(
    event_id: int,
    payload: SchoolEventUpdateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    event = db.query(SchoolEvent).filter(SchoolEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Событие не найдено")

    data = payload.model_dump(exclude_unset=True)

    if "status" in data and data["status"] is not None:
        data["status"] = EventStatusEnum(data["status"])

    for key, value in data.items():
        setattr(event, key, value)

    db.commit()
    db.refresh(event)
    return event


@router.delete("/school-events/{event_id}", response_model=SimpleMessage)
def admin_delete_school_event(
    event_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    event = db.query(SchoolEvent).filter(SchoolEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Событие не найдено")

    db.delete(event)
    db.commit()
    return SimpleMessage(message=f"Событие id={event_id} удалено")


# =========================================================
# Admin School Achievements
# =========================================================
@router.get("/school-achievements", response_model=List[AchievementOut])
def admin_list_school_achievements(
    school_name: Optional[str] = None,
    target: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    q = db.query(SchoolAchievement)

    if school_name:
        q = q.filter(SchoolAchievement.school_name == school_name)

    if target:
        try:
            q = q.filter(SchoolAchievement.target == AchievementTargetEnum(target))
        except ValueError:
            raise HTTPException(status_code=400, detail="Некорректный target")

    return (
        q.order_by(SchoolAchievement.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/school-achievements/{achievement_id}", response_model=AchievementOut)
def admin_get_school_achievement(
    achievement_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    achievement = (
        db.query(SchoolAchievement)
        .filter(SchoolAchievement.id == achievement_id)
        .first()
    )

    if not achievement:
        raise HTTPException(status_code=404, detail="Достижение не найдено")

    return achievement


@router.post(
    "/school-achievements",
    response_model=AchievementOut,
    status_code=status.HTTP_201_CREATED,
)
def admin_create_school_achievement(
    payload: AchievementCreateRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    final_target = AchievementTargetEnum(payload.target)
    final_grade = payload.grade

    if final_target == AchievementTargetEnum.school:
        final_grade = None

    if final_target == AchievementTargetEnum.grade and not final_grade:
        raise HTTPException(
            status_code=422,
            detail="Для target='grade' нужно указать grade",
        )

    achievement = SchoolAchievement(
        school_name=payload.school_name,
        target=final_target,
        grade=final_grade,
        title=payload.title,
        description=payload.description,
        cover_url=payload.cover_url,
        achieved_at=payload.achieved_at,
        created_by_id=current_admin.id,
    )

    db.add(achievement)
    db.commit()
    db.refresh(achievement)
    return achievement


@router.patch("/school-achievements/{achievement_id}", response_model=AchievementOut)
@router.put("/school-achievements/{achievement_id}", response_model=AchievementOut)
def admin_update_school_achievement(
    achievement_id: int,
    payload: AchievementUpdateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    achievement = (
        db.query(SchoolAchievement)
        .filter(SchoolAchievement.id == achievement_id)
        .first()
    )

    if not achievement:
        raise HTTPException(status_code=404, detail="Достижение не найдено")

    data = payload.model_dump(exclude_unset=True)

    if "target" in data and data["target"] is not None:
        data["target"] = AchievementTargetEnum(data["target"])

    new_target = data.get("target", achievement.target)
    new_grade = data.get("grade", achievement.grade)

    if new_target == AchievementTargetEnum.school:
        data["grade"] = None

    if new_target == AchievementTargetEnum.grade and not new_grade:
        raise HTTPException(
            status_code=422,
            detail="Для target='grade' нужно указать grade",
        )

    for key, value in data.items():
        setattr(achievement, key, value)

    db.commit()
    db.refresh(achievement)
    return achievement


@router.delete("/school-achievements/{achievement_id}", response_model=SimpleMessage)
def admin_delete_school_achievement(
    achievement_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    achievement = (
        db.query(SchoolAchievement)
        .filter(SchoolAchievement.id == achievement_id)
        .first()
    )

    if not achievement:
        raise HTTPException(status_code=404, detail="Достижение не найдено")

    db.delete(achievement)
    db.commit()
    return SimpleMessage(message=f"Достижение id={achievement_id} удалено")