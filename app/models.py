from datetime import datetime, date
import enum

from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    DateTime,
    Enum,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    JSON,
)
from sqlalchemy.orm import relationship

from .database import Base


class GenderEnum(str, enum.Enum):
    male = "male"
    female = "female"


class RoleEnum(str, enum.Enum):
    pupil = "pupil"
    teacher = "teacher"
    student = "student"


class ContactTypeEnum(str, enum.Enum):
    phone = "phone"
    email = "email"


class MediaTypeEnum(str, enum.Enum):
    image = "image"
    video = "video"


class ChatTypeEnum(str, enum.Enum):
    private = "private"
    group = "group"
    channel = "channel"


class MessageTypeEnum(str, enum.Enum):
    text = "text"
    post_share = "post_share"
    media = "media"


class NotificationTypeEnum(str, enum.Enum):
    new_follower = "new_follower"
    post_liked = "post_liked"
    post_commented = "post_commented"
    comment_liked = "comment_liked"
    comment_replied = "comment_replied"
    new_message = "new_message"
    post_shared = "post_shared"
    mention = "mention"          # @упоминания
    class_rating = "class_rating"  # рейтинг классов


class PushPlatformEnum(str, enum.Enum):
    android = "android"
    ios = "ios"
    web = "web"


class SupportRequestStatusEnum(str, enum.Enum):
    new = "new"
    in_progress = "in_progress"
    resolved = "resolved"


# ---------- Жалобы на контент ----------


class ReportTargetTypeEnum(str, enum.Enum):
    post = "post"
    comment = "comment"
    user = "user"
    message = "message"


class ReportReasonEnum(str, enum.Enum):
    spam = "spam"
    nudity = "nudity"          # 18+
    violence = "violence"
    hate = "hate"
    bullying = "bullying"
    illegal = "illegal"
    other = "other"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    birth_date = Column(Date, nullable=False)
    gender = Column(Enum(GenderEnum), nullable=False)
    role = Column(Enum(RoleEnum), nullable=False)

    phone = Column(String(32), unique=True, nullable=True, index=True)
    email = Column(String(255), unique=True, nullable=True, index=True)

    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)

    avatar_url = Column(String(255), nullable=True)
    school_name = Column(String(255), nullable=True)
    grade = Column(String(50), nullable=True)
    status = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    bio = Column(String(500), nullable=True)

    posts_count = Column(Integer, default=0)
    followers_count = Column(Integer, default=0)
    following_count = Column(Integer, default=0)

    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=True)

    # флаг админа
    is_admin = Column(Boolean, default=False)

    reset_code_hash = Column(String(255), nullable=True)
    reset_code_expires_at = Column(DateTime, nullable=True)

    last_seen = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    posts = relationship(
        "Post",
        back_populates="author",
        cascade="all, delete-orphan",
    )
    post_likes = relationship(
        "PostLike",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    comments = relationship(
        "Comment",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    followers = relationship(
        "Follow",
        foreign_keys="Follow.following_id",
        back_populates="following",
        cascade="all, delete-orphan",
    )
    following = relationship(
        "Follow",
        foreign_keys="Follow.follower_id",
        back_populates="follower",
        cascade="all, delete-orphan",
    )
    messages = relationship(
        "Message",
        back_populates="sender",
        cascade="all, delete-orphan",
        foreign_keys="Message.sender_id",
    )
    notifications = relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    # блокировки
    blocked_users = relationship(
        "Block",
        foreign_keys="Block.blocker_id",
        back_populates="blocker",
        cascade="all, delete-orphan",
    )
    blocked_by = relationship(
        "Block",
        foreign_keys="Block.blocked_id",
        back_populates="blocked",
        cascade="all, delete-orphan",
    )

    # push-токены
    push_tokens = relationship(
        "PushToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    # обращения в поддержку
    support_requests = relationship(
        "SupportRequest",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    # жалобы, отправленные пользователем
    reports = relationship(
        "ContentReport",
        back_populates="reporter",
        cascade="all, delete-orphan",
        foreign_keys="ContentReport.reporter_id",
    )


class RegistrationSession(Base):
    __tablename__ = "registration_sessions"

    id = Column(String(36), primary_key=True, index=True)

    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    birth_date = Column(Date, nullable=True)
    gender = Column(Enum(GenderEnum), nullable=True)
    role = Column(Enum(RoleEnum), nullable=True)

    contact_type = Column(Enum(ContactTypeEnum), nullable=True)
    contact_value = Column(String(255), nullable=True)

    verification_code_hash = Column(String(255), nullable=True)
    verification_code_expires_at = Column(DateTime, nullable=True)
    last_code_sent_at = Column(DateTime, nullable=True)
    is_contact_verified = Column(Boolean, default=False)

    password_hash = Column(String(255), nullable=True)
    username = Column(String(50), nullable=True)

    is_completed = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    content = Column(String(1000), nullable=False)

    # обложка поста (первое медиа)
    media_url = Column(String(255), nullable=True)
    media_type = Column(Enum(MediaTypeEnum), nullable=True)

    like_count = Column(Integer, default=0)
    comment_count = Column(Integer, default=0)
    is_deleted = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    author = relationship("User", back_populates="posts")
    likes = relationship(
        "PostLike",
        back_populates="post",
        cascade="all, delete-orphan",
    )
    comments = relationship(
        "Comment",
        back_populates="post",
        cascade="all, delete-orphan",
    )
    shared_messages = relationship(
        "Message",
        back_populates="post",
    )
    mentions = relationship(
        "PostMention",
        back_populates="post",
        cascade="all, delete-orphan",
    )

    # список медиа (фото/видео) для карусели
    media_items = relationship(
        "PostMedia",
        back_populates="post",
        cascade="all, delete-orphan",
        order_by="PostMedia.order",
    )


class PostMedia(Base):
    __tablename__ = "post_media"

    id = Column(Integer, primary_key=True, index=True)

    post_id = Column(
        Integer,
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    media_url = Column(String(255), nullable=False)
    media_type = Column(Enum(MediaTypeEnum), nullable=False)

    # порядок в карусели
    order = Column(Integer, default=0)

    # счётчик просмотров (актуально для видео)
    view_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    post = relationship("Post", back_populates="media_items")


class PostLike(Base):
    __tablename__ = "post_likes"

    id = Column(Integer, primary_key=True, index=True)

    post_id = Column(
        Integer,
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="uq_post_like"),
    )

    post = relationship("Post", back_populates="likes")
    user = relationship("User", back_populates="post_likes")


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)

    post_id = Column(
        Integer,
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    parent_comment_id = Column(
        Integer,
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    content = Column(String(500), nullable=False)
    is_deleted = Column(Boolean, default=False)
    like_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    post = relationship("Post", back_populates="comments")
    user = relationship("User", back_populates="comments")

    parent = relationship(
        "Comment",
        remote_side=[id],
        back_populates="replies",
    )
    replies = relationship(
        "Comment",
        back_populates="parent",
        cascade="all, delete-orphan",
    )
    likes = relationship(
        "CommentLike",
        back_populates="comment",
        cascade="all, delete-orphan",
    )
    mentions = relationship(
        "CommentMention",
        back_populates="comment",
        cascade="all, delete-orphan",
    )


class CommentLike(Base):
    __tablename__ = "comment_likes"

    id = Column(Integer, primary_key=True, index=True)

    comment_id = Column(
        Integer,
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("comment_id", "user_id", name="uq_comment_like"),
    )

    comment = relationship("Comment", back_populates="likes")
    user = relationship("User")


class Follow(Base):
    __tablename__ = "follows"

    id = Column(Integer, primary_key=True, index=True)

    follower_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    following_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("follower_id", "following_id", name="uq_follow"),
    )

    follower = relationship("User", foreign_keys=[follower_id], back_populates="following")
    following = relationship("User", foreign_keys=[following_id], back_populates="followers")


class Block(Base):
    __tablename__ = "blocks"

    id = Column(Integer, primary_key=True, index=True)

    blocker_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    blocked_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("blocker_id", "blocked_id", name="uq_block"),
    )

    blocker = relationship("User", foreign_keys=[blocker_id], back_populates="blocked_users")
    blocked = relationship("User", foreign_keys=[blocked_id], back_populates="blocked_by")


class Chat(Base):
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(Enum(ChatTypeEnum), nullable=False, default=ChatTypeEnum.private)
    title = Column(String(255), nullable=True)
    avatar_url = Column(String(255), nullable=True)

    pinned_message_id = Column(
        Integer,
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    is_deleted = Column(Boolean, default=False)

    created_by = relationship("User")

    participants = relationship(
        "ChatParticipant",
        back_populates="chat",
        cascade="all, delete-orphan",
    )

    messages = relationship(
        "Message",
        back_populates="chat",
        cascade="all, delete-orphan",
        foreign_keys="Message.chat_id",
    )

    pinned_messages = relationship(
        "PinnedMessage",
        back_populates="chat",
        cascade="all, delete-orphan",
    )


class ChatParticipant(Base):
    __tablename__ = "chat_participants"

    id = Column(Integer, primary_key=True, index=True)

    chat_id = Column(
        Integer,
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    is_admin = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    joined_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_chat_user"),
    )

    chat = relationship("Chat", back_populates="participants")
    user = relationship("User")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)

    chat_id = Column(
        Integer,
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    type = Column(Enum(MessageTypeEnum), nullable=False, default=MessageTypeEnum.text)
    content = Column(String(1000), nullable=True)

    post_id = Column(
        Integer,
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    media_url = Column(String(255), nullable=True)
    media_type = Column(Enum(MediaTypeEnum), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_deleted = Column(Boolean, default=False)

    is_edited = Column(Boolean, default=False)
    edited_at = Column(DateTime, nullable=True)

    chat = relationship(
        "Chat",
        back_populates="messages",
        foreign_keys=[chat_id],
    )
    sender = relationship(
        "User",
        back_populates="messages",
        foreign_keys=[sender_id],
    )
    post = relationship("Post", back_populates="shared_messages")

    statuses = relationship(
        "MessageStatus",
        back_populates="message",
        cascade="all, delete-orphan",
    )
    reactions = relationship(
        "MessageReaction",
        back_populates="message",
        cascade="all, delete-orphan",
    )
    favorites = relationship(
        "FavoriteMessage",
        back_populates="message",
        cascade="all, delete-orphan",
    )
    pinned_in = relationship(
        "PinnedMessage",
        back_populates="message",
        cascade="all, delete-orphan",
    )


class MessageStatus(Base):
    __tablename__ = "message_statuses"

    id = Column(Integer, primary_key=True, index=True)

    message_id = Column(
        Integer,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    is_delivered = Column(Boolean, default=False)
    delivered_at = Column(DateTime, nullable=True)

    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime, nullable=True)

    is_hidden = Column(Boolean, default=False)
    hidden_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_message_status"),
    )

    message = relationship("Message", back_populates="statuses")
    user = relationship("User")


class MessageReaction(Base):
    __tablename__ = "message_reactions"

    id = Column(Integer, primary_key=True, index=True)

    message_id = Column(
        Integer,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    emoji = Column(String(8), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_message_reaction"),
    )

    message = relationship("Message", back_populates="reactions")
    user = relationship("User")


class PinnedMessage(Base):
    __tablename__ = "pinned_messages"

    id = Column(Integer, primary_key=True, index=True)

    chat_id = Column(
        Integer,
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id = Column(
        Integer,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pinned_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    pinned_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True)

    chat = relationship("Chat", back_populates="pinned_messages")
    message = relationship("Message", back_populates="pinned_in")
    pinned_by = relationship("User")


class FavoriteMessage(Base):
    __tablename__ = "favorite_messages"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id = Column(
        Integer,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "message_id", name="uq_favorite_message"),
    )

    user = relationship("User")
    message = relationship("Message", back_populates="favorites")


class PostMention(Base):
    __tablename__ = "post_mentions"

    id = Column(Integer, primary_key=True, index=True)

    post_id = Column(
        Integer,
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="uq_post_mention"),
    )

    post = relationship("Post", back_populates="mentions")
    user = relationship("User")


class CommentMention(Base):
    __tablename__ = "comment_mentions"

    id = Column(Integer, primary_key=True, index=True)

    comment_id = Column(
        Integer,
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("comment_id", "user_id", name="uq_comment_mention"),
    )

    comment = relationship("Comment", back_populates="mentions")
    user = relationship("User")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    type = Column(Enum(NotificationTypeEnum), nullable=False)

    title = Column(String(255), nullable=False)
    body = Column(String(1000), nullable=True)

    data = Column(JSON, nullable=True)

    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="notifications")


class PushToken(Base):
    __tablename__ = "push_tokens"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform = Column(Enum(PushPlatformEnum), nullable=False)
    token = Column(String(512), nullable=False)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("token", name="uq_push_token_value"),
    )

    user = relationship("User", back_populates="push_tokens")


class SupportRequest(Base):
    __tablename__ = "support_requests"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    subject = Column(String(255), nullable=True)
    message = Column(String(2000), nullable=False)
    app_version = Column(String(50), nullable=True)
    device_info = Column(String(255), nullable=True)

    status = Column(
        Enum(SupportRequestStatusEnum),
        default=SupportRequestStatusEnum.new,
        nullable=False,
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="support_requests")


class ContentReport(Base):
    __tablename__ = "content_reports"

    id = Column(Integer, primary_key=True, index=True)

    reporter_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    target_type = Column(Enum(ReportTargetTypeEnum), nullable=False)

    post_id = Column(
        Integer,
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    comment_id = Column(
        Integer,
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    target_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    message_id = Column(
        Integer,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    reason = Column(Enum(ReportReasonEnum), nullable=False)
    description = Column(String(1000), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_processed = Column(Boolean, default=False)

    reporter = relationship(
        "User",
        foreign_keys=[reporter_id],
        back_populates="reports",
    )
    post = relationship("Post", foreign_keys=[post_id])
    comment = relationship("Comment", foreign_keys=[comment_id])
    target_user = relationship("User", foreign_keys=[target_user_id])
    message = relationship("Message", foreign_keys=[message_id])
