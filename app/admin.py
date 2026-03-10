from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from .database import get_db
from .auth import get_current_user
from .models import (
    User,
    Post,
    Comment,
    Message,
    ContentReport,
    PostLike,
    Chat,
)
from .schemas import (
    AdminUserListResponse,
    AdminUserShort,
    AdminDashboardOut,
    AdminReportItem,
    AdminReportListResponse,
    AdminReportActionRequest,
    SimpleMessage,
    PostOut,
)

router = APIRouter(prefix="/admin", tags=["admin"])


# --------- helper: только для админов --------- #

def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешён только администраторам",
        )
    return current_user


# --------- 1️⃣ дашборд (Статистика) --------- #

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

    # Дополнительная статистика по ТЗ
    likes_count = db.query(PostLike).count()
    active_chats = db.query(Chat).filter(Chat.is_deleted.is_(False)).count()

    reports_open = db.query(ContentReport).filter(
        ContentReport.is_processed.is_(False)
    ).count()

    # Мы возвращаем расширенный объект, Pydantic отфильтрует лишнее или мы обновим схему
    return {
        "users_total": users_total,
        "users_active": users_active,
        "posts_total": posts_total,
        "comments_total": comments_total,
        "messages_total": messages_total,
        "reports_open": reports_open,
        "likes_count": likes_count,  # Для фронтенда
        "active_chats": active_chats  # Для фронтенда
    }


# --------- 2️⃣ управление пользователями --------- #

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

    items = [AdminUserShort.from_orm(u) for u in users]
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
    db.add(user)
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
    db.add(user)
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


# --------- 3️⃣ жалобы (Reports) --------- #

@router.get("/reports", response_model=AdminReportListResponse)
def admin_list_reports(
        only_open: bool = True,
        db: Session = Depends(get_db),
        _: User = Depends(get_current_admin),
):
    query = db.query(ContentReport)
    if only_open:
        query = query.filter(ContentReport.is_processed.is_(False))

    reports: List[ContentReport] = (
        query.order_by(ContentReport.created_at.desc()).all()
    )

    items = [AdminReportItem.from_orm(r) for r in reports]
    return AdminReportListResponse(items=items)


@router.post("/reports/{report_id}/action", response_model=SimpleMessage)
def admin_process_report(
        report_id: int,
        data: AdminReportActionRequest,
        db: Session = Depends(get_db),
        admin: User = Depends(get_current_admin),
):
    report = (
        db.query(ContentReport)
        .filter(ContentReport.id == report_id)
        .first()
    )
    if not report:
        raise HTTPException(status_code=404, detail="Жалоба не найдена")

    action = data.action

    if action == "delete_post":
        if not report.post_id:
            raise HTTPException(status_code=400, detail="У жалобы нет связанного поста")
        post = db.query(Post).filter(Post.id == report.post_id).first()
        if post:
            post.is_deleted = True
            db.add(post)

    elif action == "delete_comment":
        if not report.comment_id:
            raise HTTPException(status_code=400, detail="У жалобы нет связанного комментария")
        comment = db.query(Comment).filter(Comment.id == report.comment_id).first()
        if comment:
            comment.is_deleted = True
            db.add(comment)

    elif action == "delete_message":
        if not report.message_id:
            raise HTTPException(status_code=400, detail="У жалобы нет связанного сообщения")
        message = db.query(Message).filter(Message.id == report.message_id).first()
        if message:
            message.is_deleted = True
            db.add(message)

    elif action == "ban_user":
        target_user_id = data.ban_user_id or report.target_user_id
        if not target_user_id:
            raise HTTPException(status_code=400, detail="Не указан пользователь для блокировки")
        user = db.query(User).filter(User.id == target_user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        user.is_active = False
        db.add(user)

    report.is_processed = True
    db.add(report)
    db.commit()

    return SimpleMessage(
        message=f"Жалоба id={report_id} обработана действием '{action}'"
    )


# --------- 4️⃣ модерация постов --------- #

@router.get("/posts", response_model=List[PostOut])
def admin_list_posts(
        limit: int = 50,
        offset: int = 0,
        db: Session = Depends(get_db),
        _: User = Depends(get_current_admin),
):
    # Админ видит даже скрытые/удаленные для аудита (опционально)
    posts = db.query(Post).order_by(Post.created_at.desc()).offset(offset).limit(limit).all()
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
    db.add(post)
    db.commit()
    return SimpleMessage(message=f"Пост id={post_id} удалён модератором")