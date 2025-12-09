# app/mentions.py
import re
from typing import List, Set

from sqlalchemy.orm import Session

from .models import User, PostMention, CommentMention, NotificationTypeEnum
from .notifications import create_notification

MENTION_REGEX = re.compile(r"@([A-Za-z0-9_]+)")


def extract_usernames(text: str) -> List[str]:
    """
    Парсим @username из текста.
    Разрешаем только латиницу, цифры и '_'.
    """
    if not text:
        return []
    usernames = MENTION_REGEX.findall(text)
    # убираем дубли
    return list(dict.fromkeys(usernames))


def _get_users_by_usernames(db: Session, usernames: List[str]) -> List[User]:
    if not usernames:
        return []
    return (
        db.query(User)
        .filter(User.username.in_(usernames), User.is_active == True)  # noqa
        .all()
    )


def create_post_mentions(db: Session, post, author: User):
    """
    Обновляем упоминания в посте + создаём уведомления.
    Вызывается после создания/редактирования поста.
    """
    usernames = extract_usernames(post.content)
    if not usernames:
        # очищаем старые упоминания, если их больше нет
        db.query(PostMention).filter(PostMention.post_id == post.id).delete()
        db.commit()
        return

    # удаляем старые упоминания для этого поста
    db.query(PostMention).filter(PostMention.post_id == post.id).delete()

    users = _get_users_by_usernames(db, usernames)

    for u in users:
        db.add(PostMention(post_id=post.id, user_id=u.id))

        if u.id != author.id:
            create_notification(
                db=db,
                user_id=u.id,
                type=NotificationTypeEnum.mention,
                title="Упоминание в посте",
                body=f"{author.first_name} (@{author.username}) упомянул вас в посте",
                data={"post_id": post.id},
            )

    db.commit()


def create_comment_mentions(db: Session, comment, author: User):
    """
    Обновляем упоминания в комментарии + создаём уведомления.
    Вызывается после создания комментария (и может вызываться после редактирования).
    """
    usernames = extract_usernames(comment.content)
    if not usernames:
        db.query(CommentMention).filter(CommentMention.comment_id == comment.id).delete()
        db.commit()
        return

    db.query(CommentMention).filter(CommentMention.comment_id == comment.id).delete()

    users = _get_users_by_usernames(db, usernames)

    for u in users:
        db.add(CommentMention(comment_id=comment.id, user_id=u.id))

        if u.id != author.id:
            create_notification(
                db=db,
                user_id=u.id,
                type=NotificationTypeEnum.mention,
                title="Упоминание в комментарии",
                body=f"{author.first_name} (@{author.username}) упомянул вас в комментарии",
                data={"post_id": comment.post_id, "comment_id": comment.id},
            )

    db.commit()
