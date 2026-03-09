# app/feed.py

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import get_db
from .auth import get_current_user
from .models import User, Post, Follow, PostLike

# ВАЖНО: теперь prefix="/posts", чтобы получился путь /posts/feed
router = APIRouter(
    prefix="/posts",
    tags=["feed"],
)


class FeedPostAuthor(BaseModel):
    id: int
    username: str
    full_name: str
    avatar_url: str | None
    is_following: bool


class FeedPostItem(BaseModel):
    id: int
    content: str
    media_url: str | None
    media_type: str | None
    created_at: datetime
    like_count: int
    comment_count: int
    is_liked: bool
    author: FeedPostAuthor


class FeedResponse(BaseModel):
    items: List[FeedPostItem]


@router.get("/feed", response_model=FeedResponse)
def get_feed(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):


    # все, на кого подписан текущий пользователь
    following_ids = {
        f.following_id
        for f in db.query(Follow).filter(Follow.follower_id == current_user.id).all()
    }

    # все посты, которые текущий пользователь лайкнул
    liked_post_ids = {
        pl.post_id
        for pl in db.query(PostLike).filter(PostLike.user_id == current_user.id).all()
    }

    # базовый запрос по постам
    posts = (
        db.query(Post)
        .filter(Post.is_deleted.is_(False))
        .order_by(Post.created_at.desc())
        .offset(offset)
        .limit(limit * 2)
        .all()
    )

    # сортируем: сначала посты от тех, на кого подписан, затем остальные
    posts_sorted = sorted(
        posts,
        key=lambda p: ((p.user_id in following_ids), p.created_at),
        reverse=True,
    )[:limit]

    items: List[FeedPostItem] = []

    for p in posts_sorted:
        author: User = p.author

        items.append(
            FeedPostItem(
                id=p.id,
                content=p.content,
                media_url=p.media_url,
                media_type=p.media_type.value if p.media_type else None,
                created_at=p.created_at,
                like_count=p.like_count,
                comment_count=p.comment_count,
                is_liked=p.id in liked_post_ids,
                author=FeedPostAuthor(
                    id=author.id,
                    username=author.username,
                    full_name=f"{author.first_name} {author.last_name}",
                    avatar_url=author.avatar_url,
                    is_following=author.id in following_ids,
                ),
            )
        )

    return FeedResponse(items=items)
