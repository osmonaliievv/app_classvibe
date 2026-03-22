import os
import subprocess
from datetime import datetime
from typing import List
from uuid import uuid4

from sqlalchemy.orm import Session, joinedload

from fastapi import (
    APIRouter,
    Depends,
    status,
    UploadFile,
    File,
    HTTPException,
    Response,
)

from .database import get_db
from .auth import get_current_user
from . import models
from .models import (
    Post,
    PostLike,
    PostView,
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

MAX_IMAGE_SIZE_MB = 12
MAX_VIDEO_SIZE_MB = 50

MAX_IMAGE_SIZE_BYTES = MAX_IMAGE_SIZE_MB * 1024 * 1024
MAX_VIDEO_SIZE_BYTES = MAX_VIDEO_SIZE_MB * 1024 * 1024


def _guess_extension(content_type: str, original_filename: str = "") -> str:
    content_type = (content_type or "").lower()
    original_filename = (original_filename or "").lower()

    ext = os.path.splitext(original_filename)[1].lower()
    if ext:
        return ext

    image_map = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/heic": ".heic",
        "image/heif": ".heif",
    }

    video_map = {
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/x-m4v": ".m4v",
        "video/webm": ".webm",
        "video/x-msvideo": ".avi",
        "video/avi": ".avi",
    }

    if content_type in image_map:
        return image_map[content_type]

    if content_type in video_map:
        return video_map[content_type]

    if content_type.startswith("image/"):
        return ".jpg"

    if content_type.startswith("video/"):
        return ".mp4"

    return ""


async def _validate_media_upload(file: UploadFile):
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

    return contents, media_type, content_type


def _save_file_bytes(path: str, contents: bytes):
    with open(path, "wb") as f:
        f.write(contents)


def _convert_video_to_mp4(input_path: str, output_path: str):
    ffmpeg_candidates = [
        "ffmpeg",
        r"C:\Users\Huawei\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe",
    ]

    errors = []

    for ffmpeg_path in ffmpeg_candidates:
        cmd = [
            ffmpeg_path,
            "-y",
            "-i",
            input_path,
            "-vcodec",
            "libx264",
            "-acodec",
            "aac",
            "-movflags",
            "+faststart",
            "-preset",
            "medium",
            "-crf",
            "23",
            output_path,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            errors.append(f"Не найден ffmpeg по пути: {ffmpeg_path}")
            continue

        if result.returncode == 0:
            return

        errors.append(
            f"ffmpeg найден по пути: {ffmpeg_path}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    raise HTTPException(
        status_code=500,
        detail=" | ".join(errors) if errors else "Не удалось запустить ffmpeg",
    )


def _calc_feed_score(
    *,
    post: Post,
    author: User,
    current_user: User,
    is_followed: bool,
    now: datetime,
) -> float:
    like_count = post.like_count or 0
    comment_count = post.comment_count or 0
    base_score = like_count * 2 + comment_count * 3

    age_hours = (now - post.created_at).total_seconds() / 3600.0
    if age_hours < 2:
        recency_boost = 20
    elif age_hours < 24:
        recency_boost = 10
    elif age_hours < 72:
        recency_boost = 5
    else:
        recency_boost = 0

    if post.user_id == current_user.id:
        friend_boost = 25
    elif is_followed:
        friend_boost = 15
    else:
        friend_boost = 0

    same_school = (
        author.school_name
        and current_user.school_name
        and author.school_name == current_user.school_name
    )
    school_boost = 5 if same_school else 0

    return base_score + recency_boost + friend_boost + school_boost


def _attach_post_info(post: Post, current_user_id: int, db: Session):
    is_liked = (
        db.query(PostLike)
        .filter(
            PostLike.post_id == post.id,
            PostLike.user_id == current_user_id,
        )
        .first()
        is not None
    )

    share_count = (
        db.query(Message)
        .filter(
            Message.post_id == post.id,
            Message.type == MessageTypeEnum.post_share,
        )
        .count()
    )

    post.is_liked = is_liked
    post.share_count = share_count
    return post


@router.post("/", response_model=PostOut, status_code=status.HTTP_201_CREATED)
def create_post(
    payload: PostCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    post = Post(
        user_id=current_user.id,
        content=payload.content,
        media_url=payload.media_url,
        media_type=payload.media_type,
    )
    db.add(post)
    db.flush()

    if current_user.posts_count is not None:
        current_user.posts_count += 1
        db.add(current_user)

    db.commit()
    db.refresh(post)

    create_post_mentions(db, post, current_user)

    return post


@router.get("/", response_model=List[PostOut])
def list_posts(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    posts = (
        db.query(Post)
        .options(joinedload(Post.author))
        .filter(Post.is_deleted == False)  # noqa
        .order_by(Post.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    for p in posts:
        _attach_post_info(p, current_user.id, db)

    return posts


@router.get("/{post_id}", response_model=PostOut)
def get_post_by_id(
    post_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    post = (
        db.query(Post)
        .options(joinedload(Post.author))
        .filter(Post.id == post_id, Post.is_deleted == False)  # noqa
        .first()
    )

    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пост не найден",
        )

    _attach_post_info(post, current_user.id, db)
    return post


@router.get("/feed", response_model=List[PostOut])
def feed(
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
    followed_ids = [f.following_id for f in follows]
    followed_set = set(followed_ids)

    query = (
        db.query(Post, User)
        .join(User, User.id == Post.user_id)
        .filter(Post.is_deleted == False)  # noqa
    )

    if followed_ids:
        allowed_ids = followed_ids + [current_user.id]
        query = query.filter(Post.user_id.in_(allowed_ids))

    raw_rows = query.order_by(Post.created_at.desc()).limit(200).all()

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
        _attach_post_info(post, current_user.id, db)
        scored.append((score, post))

    scored.sort(key=lambda x: x[0], reverse=True)

    slice_scored = scored[offset: offset + limit]
    posts = [p for _, p in slice_scored]

    return posts


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
        .options(joinedload(Post.author))
        .filter(Post.is_deleted == False, Post.user_id.in_(user_ids))  # noqa
        .order_by(Post.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    for p in posts:
        _attach_post_info(p, current_user.id, db)

    return posts


@router.patch("/{post_id}", response_model=PostOut)
def update_post(
    post_id: int,
    payload: PostUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    post = (
        db.query(Post)
        .options(joinedload(Post.author))
        .filter(Post.id == post_id, Post.is_deleted == False)  # noqa
        .first()
    )

    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пост не найден",
        )

    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа",
        )

    if payload.content is not None:
        post.content = payload.content

    if payload.media_url is not None:
        post.media_url = payload.media_url

    if payload.media_type is not None:
        post.media_type = payload.media_type

    db.add(post)
    db.commit()
    db.refresh(post)

    _attach_post_info(post, current_user.id, db)
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пост не найден",
        )

    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа",
        )

    post.is_deleted = True

    if current_user.posts_count and current_user.posts_count > 0:
        current_user.posts_count -= 1
        db.add(current_user)

    db.add(post)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/upload-image", response_model=PostMediaUploadResponse)
async def upload_post_media(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    contents, media_type, content_type = await _validate_media_upload(file)

    ext = _guess_extension(content_type, file.filename or "")

    allowed_image_exts = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"]
    allowed_video_exts = [".mp4", ".mov", ".m4v", ".avi", ".webm"]

    if media_type == MediaTypeEnum.image and ext not in allowed_image_exts:
        ext = ".jpg"

    if media_type == MediaTypeEnum.video and ext not in allowed_video_exts:
        ext = ".mp4"

    save_dir = os.path.join(MEDIA_ROOT, POSTS_SUBDIR)
    os.makedirs(save_dir, exist_ok=True)

    filename = f"post_{current_user.id}_{uuid4().hex}{ext}"
    save_path = os.path.join(save_dir, filename)
    _save_file_bytes(save_path, contents)

    media_url = f"/media/{POSTS_SUBDIR}/{filename}"
    return PostMediaUploadResponse(
        media_url=media_url,
        media_type=media_type,
    )


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пост не найден",
        )

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пост не найден",
        )

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

    create_comment_mentions(db, comment, current_user)

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пост не найден",
        )

    comments = (
        db.query(Comment)
        .options(joinedload(Comment.user))
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пост не найден",
        )

    if not payload.recipient_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нужно указать получателей",
        )

    unique_recipient_ids = set(payload.recipient_ids)

    for rid in unique_recipient_ids:
        if rid == current_user.id:
            continue

        chat = get_or_create_direct_chat(db, current_user.id, rid)

        now = datetime.utcnow()
        msg = Message(
            chat_id=chat.id,
            sender_id=current_user.id,
            type=MessageTypeEnum.post_share,
            content=payload.message or "",
            post_id=post.id,
            created_at=now,
        )
        db.add(msg)
        db.flush()

        status_row = models.MessageStatus(
            message_id=msg.id,
            user_id=rid,
            is_delivered=True,
            delivered_at=now,
        )
        db.add(status_row)

        chat.updated_at = now
        db.add(chat)

        create_notification(
            db=db,
            user_id=rid,
            type=NotificationTypeEnum.post_shared,
            title="С вами поделились постом",
            body=f"{current_user.first_name} {current_user.last_name} (@{current_user.username}) отправил вам пост",
            data={
                "post_id": post.id,
                "chat_id": chat.id,
                "message_id": msg.id,
                "from_user_id": current_user.id,
            },
        )

    db.commit()
    return SimpleMessage(message="Пост отправлен")


@router.post("/media/{media_id}/view", response_model=SimpleMessage)
def add_media_view(
    media_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Медиа не найдено",
        )

    if media.media_type != MediaTypeEnum.video:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Просмотры считаются только для видео",
        )

    media.view_count += 1
    db.add(media)
    db.commit()

    return SimpleMessage(message="Просмотр засчитан")


@router.post("/{post_id}/view", response_model=SimpleMessage)
def add_post_view(
    post_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    post = (
        db.query(Post)
        .filter(
            Post.id == post_id,
            Post.is_deleted == False,  # noqa
        )
        .first()
    )

    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")

    existing_view = (
        db.query(PostView)
        .filter(
            PostView.post_id == post_id,
            PostView.user_id == current_user.id,
        )
        .first()
    )

    if existing_view:
        return SimpleMessage(message="Просмотр уже был засчитан")

    new_view = PostView(
        post_id=post_id,
        user_id=current_user.id,
    )
    db.add(new_view)

    if post.view_count is None:
        post.view_count = 0

    post.view_count += 1
    db.add(post)
    db.commit()

    return SimpleMessage(message="Просмотр засчитан")