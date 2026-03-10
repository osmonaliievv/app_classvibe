from datetime import date, datetime, timezone
from typing import Optional, List, Dict, Literal

from pydantic import BaseModel, EmailStr, Field, validator

from .models import (
    GenderEnum,
    RoleEnum,
    ContactTypeEnum,
    MediaTypeEnum,
    ChatTypeEnum,
    MessageTypeEnum,
    NotificationTypeEnum,
    PushPlatformEnum,
    ReportTargetTypeEnum,
    ReportReasonEnum,
)


# ---------- Общие ----------


class Token(BaseModel):
    access_token: str
    refresh_token: str  # Добавили для эффекта Instagram
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserBase(BaseModel):
    id: int
    first_name: str
    last_name: str
    birth_date: date
    gender: GenderEnum
    role: RoleEnum
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    username: str
    avatar_url: Optional[str] = None
    school_name: Optional[str] = None
    grade: Optional[str] = None
    status: Optional[str] = None
    city: Optional[str] = None
    bio: Optional[str] = None
    posts_count: int = 0
    followers_count: int = 0
    following_count: int = 0
    is_following: bool = False

    class Config:
        from_attributes = True


class UserShort(BaseModel):
    id: int
    username: str
    first_name: str
    last_name: str
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True


class SimpleMessage(BaseModel):
    message: str


# ---------- Аутентификация / регистрация ----------


class LoginRequest(BaseModel):
    identifier: str = Field(..., description="Телефон, email или username")
    password: str


class LoginResponse(BaseModel):
    user: UserBase
    token: Token


class RegistrationSessionResponse(BaseModel):
    registration_id: str


class ResendCodeRequest(BaseModel):
    registration_id: str


class RegisterBioRequest(BaseModel):
    first_name: str
    last_name: str
    birth_date: date
    gender: GenderEnum


class RegisterRoleRequest(BaseModel):
    registration_id: str
    role: RoleEnum


class RegisterContactRequest(BaseModel):
    registration_id: str
    contact_type: ContactTypeEnum
    contact_value: str


class VerifyCodeRequest(BaseModel):
    registration_id: str
    code: str = Field(..., min_length=4, max_length=4)


class RegisterPasswordRequest(BaseModel):
    registration_id: str
    password: str = Field(..., min_length=8)
    password_confirm: str = Field(..., min_length=8)


class RegisterUsernameRequest(BaseModel):
    session_id: Optional[str] = None
    registration_id: Optional[str] = None
    username: str = Field(..., min_length=3, max_length=50)

    @validator("username")
    def username_allowed_chars(cls, v: str) -> str:
        import re
        if not re.fullmatch(r"[a-z0-9._]+", v):
            raise ValueError("Разрешены только маленькие латинские буквы, цифры, '.', '_'")
        return v


class UsernameCheckResponse(BaseModel):
    username: str
    available: bool


class ForgotPasswordRequest(BaseModel):
    identifier: str


class ForgotPasswordConfirmRequest(BaseModel):
    identifier: str
    code: str = Field(..., min_length=4, max_length=4)
    new_password: str = Field(..., min_length=8)
    new_password_confirm: str = Field(..., min_length=8)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8)
    new_password_confirm: str = Field(..., min_length=8)


# ---------- Профиль ----------


class ProfileUpdateRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    school_name: Optional[str] = None
    grade: Optional[str] = None
    status: Optional[str] = None
    city: Optional[str] = None
    bio: Optional[str] = None
    role: Optional[RoleEnum] = None


class ChangeUsernameRequest(BaseModel):
    new_username: str = Field(..., min_length=3, max_length=50)

    @validator("new_username")
    def username_allowed_chars(cls, v: str) -> str:
        import re
        if not re.fullmatch(r"[a-z0-9._]+", v):
            raise ValueError("Разрешены только маленькие латинские буквы, цифры, '.', '_'")
        return v


# ---------- Посты / комментарии ----------


class PostBase(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)


class PostCreate(PostBase):
    media_url: Optional[str] = None
    media_type: Optional[MediaTypeEnum] = None


class PostUpdate(BaseModel):
    content: Optional[str] = Field(None, min_length=1, max_length=1000)
    media_url: Optional[str] = None
    media_type: Optional[MediaTypeEnum] = None


class PostOut(PostBase):
    id: int
    media_url: Optional[str] = None
    media_type: Optional[MediaTypeEnum] = None
    like_count: int
    comment_count: int
    view_count: int = 0
    share_count: int = 0
    is_liked: bool = False
    created_at: datetime
    author: Optional[UserShort] = None

    class Config:
        from_attributes = True

    @validator("created_at", pre=True)
    def ensure_utc(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class PostMediaUploadResponse(BaseModel):
    media_url: str
    media_type: MediaTypeEnum


class LikeResponse(BaseModel):
    liked: bool
    like_count: int


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=500)
    parent_comment_id: Optional[int] = None


class CommentOut(BaseModel):
    id: int
    post_id: int
    user_id: int
    parent_comment_id: Optional[int] = None
    content: str
    like_count: int
    created_at: datetime
    user: Optional[UserShort] = None

    class Config:
        from_attributes = True

    @validator("created_at", pre=True)
    def ensure_utc(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class CommentLikeResponse(BaseModel):
    liked: bool
    like_count: int


# ---------- Чаты ----------


class ChatOut(BaseModel):
    id: int
    type: ChatTypeEnum
    title: Optional[str] = None
    avatar_url: Optional[str] = None
    last_message_preview: Optional[str] = None
    last_message_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MessageBase(BaseModel):
    type: MessageTypeEnum = MessageTypeEnum.text
    content: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[MediaTypeEnum] = None


class MessageCreate(MessageBase):
    pass


class MessageOut(BaseModel):
    id: int
    chat_id: int
    sender_id: Optional[int]
    sender: Optional[UserShort] = None
    type: MessageTypeEnum
    content: Optional[str]
    post_id: Optional[int]
    media_url: Optional[str]
    media_type: Optional[MediaTypeEnum]
    created_at: datetime
    is_deleted: bool
    is_edited: bool
    edited_at: Optional[datetime] = None

    read_count: Optional[int] = None
    is_read_by_me: Optional[bool] = None

    class Config:
        from_attributes = True

    @validator("created_at", pre=True)
    def ensure_utc(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class SharePostRequest(BaseModel):
    recipient_ids: List[int]
    message: Optional[str] = None


class ChatCreateBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    participant_ids: List[int] = Field(default_factory=list)


class GroupChatCreateRequest(ChatCreateBase):
    pass


class ChannelChatCreateRequest(ChatCreateBase):
    pass


class ChatUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)


class MessageEditRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)


class MessageDeleteRequest(BaseModel):
    delete_forall: bool = False


class ReactionRequest(BaseModel):
    emoji: Optional[str] = None

    @validator("emoji")
    def allowed_emoji(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        allowed = {"🔥", "😂", "❤️", "👍"}
        if v not in allowed:
            raise ValueError("Разрешены только эмодзи: 🔥 😂 ❤️ 👍")
        return v


class MessageReadRequest(BaseModel):
    message_ids: Optional[List[int]] = None
    up_to_message_id: Optional[int] = None


class FavoriteToggleResponse(BaseModel):
    is_favorite: bool


class PinnedMessageOut(BaseModel):
    id: int
    chat_id: int
    message_id: int
    pinned_by_id: Optional[int]
    pinned_at: datetime
    is_active: bool

    class Config:
        from_attributes = True


class ParticipantShort(BaseModel):
    user_id: int
    first_name: str
    last_name: str
    username: str
    avatar_url: Optional[str] = None
    is_admin: bool
    is_banned: bool

    class Config:
        from_attributes = True


# ------ Уведомления ------


class NotificationOut(BaseModel):
    id: int
    type: NotificationTypeEnum
    title: str
    body: Optional[str] = None
    data: Optional[Dict] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True

    @validator("created_at", pre=True)
    def ensure_utc(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


# ------ Push / FCM ------


class PushRegisterRequest(BaseModel):
    platform: PushPlatformEnum
    token: str


# ------ Админка: пользователи, жалобы, дашборд ------


class AdminUserShort(BaseModel):
    id: int
    username: str
    first_name: str
    last_name: str
    role: RoleEnum
    is_active: bool
    is_admin: bool
    created_at: datetime
    last_seen: Optional[datetime] = None

    class Config:
        from_attributes = True


class AdminUserListResponse(BaseModel):
    items: List[AdminUserShort]


class AdminDashboardOut(BaseModel):
    users_total: int
    users_active: int
    posts_total: int
    comments_total: int
    messages_total: int
    reports_open: int


class AdminReportItem(BaseModel):
    id: int
    reporter_id: Optional[int]
    target_type: ReportTargetTypeEnum
    post_id: Optional[int]
    comment_id: Optional[int]
    target_user_id: Optional[int]
    message_id: Optional[int]
    reason: ReportReasonEnum
    description: Optional[str]
    is_processed: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AdminReportListResponse(BaseModel):
    items: List[AdminReportItem]


class AdminReportActionRequest(BaseModel):
    action: Literal[
        "ignore",
        "delete_post",
        "delete_comment",
        "delete_message",
        "ban_user",
    ]
    ban_user_id: Optional[int] = None
    note: Optional[str] = None


# ==========================
# ✅ Жизнь школы (School Life) — схемы экрана
# ==========================

class SchoolEventOut(BaseModel):
    id: int
    title: str
    cover_url: Optional[str] = None
    starts_at: datetime
    ends_at: Optional[datetime] = None
    location: Optional[str] = None
    status: Optional[str] = None

    class Config:
        from_attributes = True


class SchoolEventCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    cover_url: Optional[str] = None
    starts_at: datetime
    ends_at: Optional[datetime] = None
    location: Optional[str] = None
    description: Optional[str] = Field(None, max_length=2000)
    status: Optional[Literal["draft", "published", "cancelled"]] = "published"
    school_name: Optional[str] = None


class SchoolEventUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    cover_url: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    location: Optional[str] = None
    description: Optional[str] = Field(None, max_length=2000)
    status: Optional[Literal["draft", "published", "cancelled"]] = None
    school_name: Optional[str] = None


class AchievementOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    cover_url: Optional[str] = None
    achieved_at: Optional[datetime] = None
    target: str
    grade: Optional[str] = None

    class Config:
        from_attributes = True


class AchievementCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    cover_url: Optional[str] = None
    achieved_at: Optional[datetime] = None
    target: Literal["school", "grade"] = "school"
    grade: Optional[str] = None
    school_name: Optional[str] = None


class AchievementUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    cover_url: Optional[str] = None
    achieved_at: Optional[datetime] = None
    target: Optional[Literal["school", "grade"]] = None
    grade: Optional[str] = None
    school_name: Optional[str] = None


class ActiveClassItem(BaseModel):
    grade: str
    status: Literal["creative", "study", "friendly", "creative_art", "sport"]
    label: str


class SchoolLifeResponse(BaseModel):
    school_name: str
    events: List[SchoolEventOut]
    best_posts: List[PostOut]
    active_classes: List[ActiveClassItem]
    achievements: List[AchievementOut]
    week_start: datetime
    week_end: datetime