# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
import os

from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import select

from .database import engine, SessionLocal
from .models import (
    User,
    Post,
    ContentReport,
    SchoolEvent,
    SchoolAchievement,
)
from . import models
from .config import SECRET_KEY
from .auth import verify_password
from .auth import router as auth_router
from .profile import router as profile_router
from .posts import router as posts_router
from .social import router as social_router
from .chats import router as chats_router
from .users import router as users_router
from .notifications import router as notifications_router
from .block import router as block_router
from .settings import router as settings_router
from .reports import router as reports_router
from .admin import router as admin_router
from .school_life import router as school_life_router

app = FastAPI(title="ClassVibe API", version="1.0.0")


# =========================================================
# Helpers
# =========================================================
def is_super_admin(request: Request) -> bool:
    return bool(request.session.get("is_admin", False))


def is_school_admin(request: Request) -> bool:
    return bool(request.session.get("is_school_admin", False))


def current_school_name(request: Request) -> str | None:
    return request.session.get("school_name")


# =========================================================
# SQLAdmin auth backend
# =========================================================
class AdminAuth(AuthenticationBackend):
    def __init__(self, secret_key: str):
        super().__init__(secret_key=secret_key)

    async def login(self, request: Request) -> bool:
        form = await request.form()
        identifier = (form.get("username") or "").strip()
        password = form.get("password") or ""

        if not identifier or not password:
            return False

        db = SessionLocal()
        try:
            user = (
                db.query(User)
                .filter(
                    (User.username == identifier)
                    | (User.email == identifier)
                    | (User.phone == identifier)
                )
                .first()
            )

            if not user:
                return False

            if not user.is_active:
                return False

            if not (user.is_admin or getattr(user, "is_school_admin", False)):
                return False

            if not verify_password(password, user.password_hash):
                return False

            request.session["admin_user_id"] = user.id
            request.session["admin_username"] = user.username
            request.session["is_admin"] = bool(user.is_admin)
            request.session["is_school_admin"] = bool(getattr(user, "is_school_admin", False))
            request.session["school_name"] = user.school_name
            return True

        finally:
            db.close()

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        admin_user_id = request.session.get("admin_user_id")
        if not admin_user_id:
            return False

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == admin_user_id).first()
            if not user:
                request.session.clear()
                return False

            if not user.is_active:
                request.session.clear()
                return False

            if not (user.is_admin or getattr(user, "is_school_admin", False)):
                request.session.clear()
                return False

            request.session["is_admin"] = bool(user.is_admin)
            request.session["is_school_admin"] = bool(getattr(user, "is_school_admin", False))
            request.session["school_name"] = user.school_name
            return True

        finally:
            db.close()


admin_auth = AdminAuth(secret_key=SECRET_KEY)

# =========================================================
# Middlewares
# =========================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
)

# =========================================================
# SQLAdmin visual admin panel
# =========================================================
admin = Admin(
    app,
    engine,
    authentication_backend=admin_auth,
    title="ClassVibe Admin Panel",
)


class UserAdmin(ModelView, model=User):
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-user"
    category = "Platform"

    column_list = [
        User.id,
        User.username,
        User.first_name,
        User.last_name,
        User.school_name,
        User.is_admin,
        User.is_school_admin,
        User.is_active,
    ]
    column_searchable_list = [User.username, User.email]

    def is_visible(self, request: Request) -> bool:
        return is_super_admin(request)

    def is_accessible(self, request: Request) -> bool:
        return is_super_admin(request)


class PostAdmin(ModelView, model=Post):
    name = "Post"
    name_plural = "Posts"
    icon = "fa-solid fa-newspaper"
    category = "Platform"

    column_list = [
        Post.id,
        Post.user_id,
        Post.content,
        Post.like_count,
        Post.is_deleted,
        Post.created_at,
    ]
    column_searchable_list = [Post.content]

    def is_visible(self, request: Request) -> bool:
        return is_super_admin(request)

    def is_accessible(self, request: Request) -> bool:
        return is_super_admin(request)


class ReportAdmin(ModelView, model=ContentReport):
    name = "Content Report"
    name_plural = "Content Reports"
    icon = "fa-solid fa-flag"
    category = "Platform"

    column_list = [
        ContentReport.id,
        ContentReport.target_type,
        ContentReport.reason,
        ContentReport.is_processed,
    ]

    def is_visible(self, request: Request) -> bool:
        return is_super_admin(request)

    def is_accessible(self, request: Request) -> bool:
        return is_super_admin(request)


class SchoolEventAdmin(ModelView, model=SchoolEvent):
    name = "School Event"
    name_plural = "School Events"
    icon = "fa-solid fa-calendar-days"
    category = "School Life"

    column_list = [
        SchoolEvent.id,
        SchoolEvent.title,
        SchoolEvent.school_name,
        SchoolEvent.status,
        SchoolEvent.starts_at,
        SchoolEvent.created_at,
    ]
    column_searchable_list = [SchoolEvent.title, SchoolEvent.school_name]

    form_columns = [
        SchoolEvent.school_name,
        SchoolEvent.title,
        SchoolEvent.cover_url,
        SchoolEvent.starts_at,
        SchoolEvent.ends_at,
        SchoolEvent.location,
        SchoolEvent.description,
        SchoolEvent.status,
        SchoolEvent.created_by_id,
    ]

    def is_visible(self, request: Request) -> bool:
        return is_super_admin(request) or is_school_admin(request)

    def is_accessible(self, request: Request) -> bool:
        return is_super_admin(request) or is_school_admin(request)

    def list_query(self, request: Request):
        stmt = select(SchoolEvent)
        if is_super_admin(request):
            return stmt
        school_name = current_school_name(request)
        return stmt.where(SchoolEvent.school_name == school_name)

    def count_query(self, request: Request):
        stmt = select(SchoolEvent)
        if is_super_admin(request):
            return stmt
        school_name = current_school_name(request)
        return stmt.where(SchoolEvent.school_name == school_name)

    def details_query(self, request: Request):
        stmt = select(SchoolEvent)
        if is_super_admin(request):
            return stmt
        school_name = current_school_name(request)
        return stmt.where(SchoolEvent.school_name == school_name)

    async def on_model_change(self, data, model, is_created, request: Request):
        if is_school_admin(request) and not is_super_admin(request):
            model.school_name = current_school_name(request)
            model.created_by_id = request.session.get("admin_user_id")


class SchoolAchievementAdmin(ModelView, model=SchoolAchievement):
    name = "School Achievement"
    name_plural = "School Achievements"
    icon = "fa-solid fa-trophy"
    category = "School Life"

    column_list = [
        SchoolAchievement.id,
        SchoolAchievement.title,
        SchoolAchievement.school_name,
        SchoolAchievement.target,
        SchoolAchievement.grade,
        SchoolAchievement.achieved_at,
        SchoolAchievement.created_at,
    ]
    column_searchable_list = [
        SchoolAchievement.title,
        SchoolAchievement.description,
        SchoolAchievement.school_name,
        SchoolAchievement.grade,
    ]

    form_columns = [
        SchoolAchievement.school_name,
        SchoolAchievement.target,
        SchoolAchievement.grade,
        SchoolAchievement.title,
        SchoolAchievement.description,
        SchoolAchievement.cover_url,
        SchoolAchievement.achieved_at,
        SchoolAchievement.created_by_id,
    ]

    def is_visible(self, request: Request) -> bool:
        return is_super_admin(request) or is_school_admin(request)

    def is_accessible(self, request: Request) -> bool:
        return is_super_admin(request) or is_school_admin(request)

    def list_query(self, request: Request):
        stmt = select(SchoolAchievement)
        if is_super_admin(request):
            return stmt
        school_name = current_school_name(request)
        return stmt.where(SchoolAchievement.school_name == school_name)

    def count_query(self, request: Request):
        stmt = select(SchoolAchievement)
        if is_super_admin(request):
            return stmt
        school_name = current_school_name(request)
        return stmt.where(SchoolAchievement.school_name == school_name)

    def details_query(self, request: Request):
        stmt = select(SchoolAchievement)
        if is_super_admin(request):
            return stmt
        school_name = current_school_name(request)
        return stmt.where(SchoolAchievement.school_name == school_name)

    async def on_model_change(self, data, model, is_created, request: Request):
        if is_school_admin(request) and not is_super_admin(request):
            model.school_name = current_school_name(request)
            model.created_by_id = request.session.get("admin_user_id")


admin.add_view(UserAdmin)
admin.add_view(PostAdmin)
admin.add_view(ReportAdmin)
admin.add_view(SchoolEventAdmin)
admin.add_view(SchoolAchievementAdmin)

# =========================================================
# Static/media
# =========================================================
MEDIA_DIR = "media"
os.makedirs(MEDIA_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory="media"), name="media")

# =========================================================
# DB init
# =========================================================
models.Base.metadata.create_all(bind=engine)

# =========================================================
# Routers
# =========================================================
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(posts_router)
app.include_router(social_router)
app.include_router(chats_router)
app.include_router(users_router)
app.include_router(notifications_router)
app.include_router(block_router)
app.include_router(settings_router)
app.include_router(school_life_router)
app.include_router(reports_router)
app.include_router(admin_router)


# =========================================================
# Public pages
# =========================================================
@app.get("/privacy-policy")
def privacy_policy():
    return FileResponse("app/templates/privacy_policy.html")


@app.get("/")
def root():
    return {"message": "ClassVibe API is running. Go to /admin for visual dashboard"}