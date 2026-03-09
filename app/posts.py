import os
from datetime import datetime
from typing import List
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    status,
    UploadFile,
    File,
    HTTPException,
    Response,
)
from sqlalchemy.orm import Session

from .database import get_db
from .auth import get_current_user
from .models import (
    Post,
    PostLike,
    Comment,
    CommentLike,
    MediaTypeEnum,
    Follow,
    Message,
    MessageTypeEnum,
    NotificationTypeEnum,
    User,
    PostMedia,
)
from .schemas import (
    PostCreate,
    PostUpdate,
    PostOut,
    PostMediaUploadResponse,
    LikeResponse,
    CommentCreate,
    CommentOut,
    CommentLikeResponse,
    SharePostRequest,
    SimpleMessage,
)
from .chats import get_or_create_direct_chat
from .notifications import create_notification
from .mentions import create_post_mentions, create_comment_mentions

router = APIRouter(prefix="/posts", tags=["posts"])

MEDIA_ROOT = "media"
POSTS_SUBDIR = "posts"
os.makedirs(os.path.join(MEDIA_ROOT, POSTS_SUBDIR), exist_ok=True)

MAX_IMAGE_SIZE_MB = 5
MAX_VIDEO_SIZE_MB = 30

MAX_IMAGE_SIZE_BYTES = MAX_IMAGE_SIZE_MB * 1024 * 1024
MAX_VIDEO_SIZE_BYTES = MAX_VIDEO_SIZE_MB * 1024 * 1024


async def _validate_media_upload(file: UploadFile):
    """
    Проверяем тип и размер файла.
    Возвращаем (bytes, MediaTypeEnum).
    """
    contents = await file.read()
    size = len(contents)
    content_type = (file.content_type or "").lower()

    if content_type.startswith("image/"):
        if size > MAX_IMAGE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Слишком большой файл изображения. Максимум {MAX_IMAGE_SIZE_MB} MB.",
            )
        media_type = MediaTypeEnum.image
    elif content_type.startswith("video/"):
        if size > MAX_VIDEO_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Слишком большой видеофайл. Максимум {MAX_VIDEO_SIZE_MB} MB.",
            )
        media_type = MediaTypeEnum.video
    else:
        raise HTTPException(
            status_code=400,
            detail="Разрешены только изображения и видео.",
        )

    return contents, media_type


def _calc_feed_score(
    *,
    post: Post,
    author: User,
    current_user: User,
    is_followed: bool,
    now: datetime,
) -> float:
    """
    Алгоритмический скоринг поста для ленты.

    Логика:
      - базовый вес за активность:
            like_count * 2 + comment_count * 3
      - свежие посты получают буст
      - свои посты / посты подписок получают буст
      - если одна школа — небольшой бонус
    """
    like_count = post.like_count or 0
    comment_count = post.comment_count or 0
    base_score = like_count * 2 + comment_count * 3

    # свежесть
    age_hours = (now - post.created_at).total_seconds() / 3600.0
    if age_hours < 2:
        recency_boost = 20
    elif age_hours < 24:
        recency_boost = 10
    elif age_hours < 72:
        recency_boost = 5
    else:
        recency_boost = 0

    # свои / подписки
    if post.user_id == current_user.id:
        friend_boost = 25
    elif is_followed:
        friend_boost = 15
    else:
        friend_boost = 0

    # одна школа
    same_school = (
        author.school_name
        and current_user.school_name
        and author.school_name == current_user.school_name
    )
    school_boost = 5 if same_school else 0

    return base_score + recency_boost + friend_boost + school_boost


# ------------------ СОЗДАНИЕ ПОСТА ------------------ #


@router.post("/", response_model=PostOut, status_code=status.HTTP_201_CREATED)
def create_post(
    payload: PostCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # ✅ создаём пост (одиночное медиа: media_url + media_type)
    post = Post(
        user_id=current_user.id,
        content=payload.content,
        media_url=payload.media_url,
        media_type=payload.media_type,
    )
    db.add(post)
    db.flush()  # получаем post.id

    # ✅ УБРАЛИ payload.media, потому что в PostCreate его нет
    # (если хочешь галерею из нескольких медиа — сделаем позже через отдельную схему)

    if current_user.posts_count is not None:
        current_user.posts_count += 1
        db.add(current_user)

    db.commit()
    db.refresh(post)

    # обработка @username в тексте поста
    create_post_mentions(db, post, current_user)

    return post

# ------------------ ПРОСТО СПИСОК ВСЕХ ПОСТОВ ------------------ #


@router.get("/", response_model=List[PostOut])
def list_posts(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    posts = (
        db.query(Post)
        .filter(Post.is_deleted == False)  # noqa
        .order_by(Post.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return posts


# ------------------ ОСНОВНАЯ ЛЕНТА /posts/feed ------------------ #


@router.get("/feed", response_model=List[PostOut])
def feed(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Алгоритмическая лента:

    - приоритет: свои посты + посты подписок;
    - если подписок нет — подмешиваем все посты;
    - сортировка по score:
        score = 2 * likes + 3 * comments + свежесть + буст друзей + буст одной школы
    """

    # 1) список подписок
    follows = (
        db.query(Follow)
        .filter(Follow.follower_id == current_user.id)
        .all()
    )
    followed_ids = [f.following_id for f in follows]
    followed_set = set(followed_ids)

    # 2) базовый запрос
    query = (
        db.query(Post, User)
        .join(User, User.id == Post.user_id)
        .filter(Post.is_deleted == False)  # noqa
    )

    # если есть подписки — показываем только свои + подписки
    if followed_ids:
        allowed_ids = followed_ids + [current_user.id]
        query = query.filter(Post.user_id.in_(allowed_ids))

    # 3) берём пул и сортируем в Python по score
    raw_rows = (
        query.order_by(Post.created_at.desc())
        .limit(200)
        .all()
    )

    now = datetime.utcnow()
    scored = []
    for post, author in raw_rows:
        is_followed = post.user_id in followed_set
        score = _calc_feed_score(
            post=post,
            author=author,
            current_user=current_user,
            is_followed=is_followed,
            now=now,
        )
        scored.append((score, post))

    scored.sort(key=lambda x: x[0], reverse=True)

    # применяем offset/limit к отсортированному списку
    slice_scored = scored[offset: offset + limit]
    posts = [p for _, p in slice_scored]

    return posts


# ------------------ ЛЕНТА ТОЛЬКО ДРУЗЕЙ /posts/feed/friends ------------------ #


@router.get("/feed/friends", response_model=List[PostOut])
def friends_feed(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    follows = (
        db.query(Follow)
        .filter(Follow.follower_id == current_user.id)
        .all()
    )
    user_ids = [f.following_id for f in follows] + [current_user.id]
    if not user_ids:
        return []
    posts = (
        db.query(Post)
        .filter(Post.is_deleted == False, Post.user_id.in_(user_ids))  # noqa
        .order_by(Post.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return posts


# ------------------ РЕДАКТИРОВАНИЕ / УДАЛЕНИЕ ------------------ #


@router.patch("/{post_id}", response_model=PostOut)
def update_post(
    post_id: int,
    payload: PostUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    post = (
        db.query(Post)
        .filter(Post.id == post_id, Post.is_deleted == False)  # noqa
        .first()
    )
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пост не найден")
    if post.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа")

    if payload.content is not None:
        post.content = payload.content
    if payload.media_url is not None:
        post.media_url = payload.media_url
    if payload.media_type is not None:
        post.media_type = payload.media_type

    # если передан список media — полностью пересоздаём его
    if payload.media is not None:
        # удаляем старые медиа
        for item in list(post.media_items):
            db.delete(item)
        db.flush()

        media_items = []
        for i, m in enumerate(payload.media):
            item = PostMedia(
                post_id=post.id,
                media_url=m.media_url,
                media_type=m.media_type,
                order=m.order if m.order is not None else i,
            )
            db.add(item)
            media_items.append(item)

        if media_items:
            post.media_url = media_items[0].media_url
            post.media_type = media_items[0].media_type

    db.add(post)
    db.commit()
    db.refresh(post)

    # пересоздаём упоминания
    create_post_mentions(db, post, current_user)

    return post


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    post = (
        db.query(Post)
        .filter(Post.id == post_id, Post.is_deleted == False)  # noqa
        .first()
    )
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пост не найден")
    if post.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа")

    post.is_deleted = True

    if current_user.posts_count and current_user.posts_count > 0:
        current_user.posts_count -= 1
        db.add(current_user)

    db.add(post)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------ ЗАГРУЗКА МЕДИА ------------------ #


@router.post("/upload-image", response_model=PostMediaUploadResponse)
async def upload_post_media(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    """
    Загрузка медиаданных для поста (картинка / видео).
    """
    contents, media_type = await _validate_media_upload(file)

    ext = os.path.splitext(file.filename or "")[1].lower()
    allowed_exts = [".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mov"]
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неподдерживаемый тип файла",
        )

    filename = f"post_{current_user.id}_{uuid4().hex}{ext}"
    save_dir = os.path.join(MEDIA_ROOT, POSTS_SUBDIR)
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, filename)

    with open(save_path, "wb") as f:
        f.write(contents)

    media_url = f"/media/{POSTS_SUBDIR}/{filename}"
    return PostMediaUploadResponse(media_url=media_url, media_type=media_type)


# ------------------ ЛАЙКИ/КОММЕНТАРИИ ------------------ #


@router.post("/{post_id}/like", response_model=LikeResponse)
def like_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    post = (
        db.query(Post)
        .filter(Post.id == post_id, Post.is_deleted == False)  # noqa
        .first()
    )
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пост не найден")

    existing_like = (
        db.query(PostLike)
        .filter(
            PostLike.post_id == post_id,
            PostLike.user_id == current_user.id,
        )
        .first()
    )

    liked: bool

    if existing_like:
        db.delete(existing_like)
        if post.like_count > 0:
            post.like_count -= 1
        liked = False
    else:
        like = PostLike(post_id=post_id, user_id=current_user.id)
        db.add(like)
        post.like_count += 1
        liked = True

        if post.user_id != current_user.id:
            create_notification(
                db=db,
                user_id=post.user_id,
                type=NotificationTypeEnum.post_liked,
                title="Ваш пост понравился",
                body=f"{current_user.first_name} {current_user.last_name} (@{current_user.username}) поставил лайк вашему посту",
                data={"post_id": post.id, "from_user_id": current_user.id},
            )

    db.add(post)
    db.commit()
    db.refresh(post)

    return LikeResponse(liked=liked, like_count=post.like_count)


@router.post("/{post_id}/comment", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(
    post_id: int,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    post = (
        db.query(Post)
        .filter(Post.id == post_id, Post.is_deleted == False)  # noqa
        .first()
    )
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пост не найден")

    parent_comment = None
    if payload.parent_comment_id is not None:
        parent_comment = (
            db.query(Comment)
            .filter(
                Comment.id == payload.parent_comment_id,
                Comment.post_id == post_id,
                Comment.is_deleted == False,
            )
            .first()
        )
        if not parent_comment:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Родительский комментарий не найден",
            )

    comment = Comment(
        post_id=post_id,
        user_id=current_user.id,
        content=payload.content,
        parent_comment_id=payload.parent_comment_id,
    )
    db.add(comment)
    post.comment_count += 1
    db.add(post)

    db.commit()
    db.refresh(comment)

    # обработка @username в комментарии
    create_comment_mentions(db, comment, current_user)

    # уведомления
    if post.user_id != current_user.id:
        create_notification(
            db=db,
            user_id=post.user_id,
            type=NotificationTypeEnum.post_commented,
            title="Новый комментарий к вашему посту",
            body=f"{current_user.first_name} {current_user.last_name} (@{current_user.username}) оставил комментарий",
            data={"post_id": post.id, "comment_id": comment.id, "from_user_id": current_user.id},
        )

    if parent_comment and parent_comment.user_id not in (None, current_user.id, post.user_id):
        create_notification(
            db=db,
            user_id=parent_comment.user_id,
            type=NotificationTypeEnum.comment_replied,
            title="Новый ответ на ваш комментарий",
            body=f"{current_user.first_name} {current_user.last_name} (@{current_user.username}) ответил на ваш комментарий",
            data={
                "post_id": post.id,
                "comment_id": comment.id,
                "parent_comment_id": parent_comment.id,
                "from_user_id": current_user.id,
            },
        )

    return comment


@router.get("/{post_id}/comments", response_model=List[CommentOut])
def list_comments(
    post_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    post = (
        db.query(Post)
        .filter(Post.id == post_id, Post.is_deleted == False)  # noqa
        .first()
    )
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пост не найден")

    comments = (
        db.query(Comment)
        .filter(Comment.post_id == post_id, Comment.is_deleted == False)  # noqa
        .order_by(Comment.created_at.asc())
        .all()
    )
    return comments


@router.post("/comments/{comment_id}/like", response_model=CommentLikeResponse)
def like_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    comment = (
        db.query(Comment)
        .filter(Comment.id == comment_id, Comment.is_deleted == False)  # noqa
        .first()
    )
    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Комментарий не найден",
        )

    existing_like = (
        db.query(CommentLike)
        .filter(
            CommentLike.comment_id == comment_id,
            CommentLike.user_id == current_user.id,
        )
        .first()
    )

    liked: bool

    if existing_like:
        db.delete(existing_like)
        if comment.like_count > 0:
            comment.like_count -= 1
        liked = False
    else:
        like = CommentLike(comment_id=comment_id, user_id=current_user.id)
        db.add(like)
        comment.like_count += 1
        liked = True

        if comment.user_id != current_user.id:
            create_notification(
                db=db,
                user_id=comment.user_id,
                type=NotificationTypeEnum.comment_liked,
                title="Ваш комментарий понравился",
                body=f"{current_user.first_name} {current_user.last_name} (@{current_user.username}) поставил лайк вашему комментарию",
                data={
                    "post_id": comment.post_id,
                    "comment_id": comment.id,
                    "from_user_id": current_user.id,
                },
            )

    db.add(comment)
    db.commit()
    db.refresh(comment)

    return CommentLikeResponse(liked=liked, like_count=comment.like_count)


# ------------------ ШЕРИНГ ПОСТА ------------------ #


@router.post("/{post_id}/share", response_model=SimpleMessage)
def share_post(
    post_id: int,
    payload: SharePostRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    post = (
        db.query(Post)
        .filter(Post.id == post_id, Post.is_deleted == False)  # noqa
        .first()
    )
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пост не найден")

    if not payload.recipient_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нужно указать получателей")

    for rid in payload.recipient_ids:
        chat = get_or_create_direct_chat(db, current_user.id, rid)

        now = datetime.utcnow()
        msg = Message(
            chat_id=chat.id,
            sender_id=current_user.id,
            type=MessageTypeEnum.post_share,
            content=payload.message,
            post_id=post.id,
            created_at=now,
        )
        db.add(msg)

        chat.updated_at = now
        db.add(chat)

        if rid != current_user.id:
            create_notification(
                db=db,
                user_id=rid,
                type=NotificationTypeEnum.post_shared,
                title="С вами поделились постом",
                body=f"{current_user.first_name} {current_user.last_name} (@{current_user.username}) отправил вам пост",
                data={"post_id": post.id, "chat_id": chat.id, "message_id": msg.id, "from_user_id": current_user.id},
            )

    db.commit()
    return SimpleMessage(message="Пост отправлен")


# ------------------ ПРОСМОТРЫ ВИДЕО ------------------ #


@router.post("/media/{media_id}/view", response_model=SimpleMessage)
def add_media_view(
    media_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Увеличивает счётчик просмотров для конкретного медиа (обычно видео).
    Фронт должен вызывать этот эндпоинт, когда пользователь реально посмотрел видео.
    """
    media = (
        db.query(PostMedia)
        .join(Post, PostMedia.post_id == Post.id)
        .filter(
            PostMedia.id == media_id,
            Post.is_deleted == False,  # noqa
        )
        .first()
    )
    if not media:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Медиа не найдено")

    if media.media_type != MediaTypeEnum.video:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Просмотры считаются только для видео",
        )

    media.view_count += 1
    db.add(media)
    db.commit()

    return SimpleMessage(message="Просмотр засчитан")
