from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

# --- ИМПОРТЫ ДЛЯ ВИЗУАЛЬНОЙ АДМИНКИ ---
from sqladmin import Admin, ModelView
from .database import engine
from .models import User, Post, Comment, ContentReport, SchoolEvent, SchoolAchievement

from . import models
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

# --- НАСТРОЙКА SQLADMIN ---
admin = Admin(app, engine, title="ClassVibe Admin Panel")

class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.username, User.first_name, User.last_name, User.is_admin, User.is_active]
    column_searchable_list = [User.username, User.email]
    column_filters = [User.is_admin, User.is_active, User.role]
    icon = "fa-solid fa-user"
    category = "Accounts"

class PostAdmin(ModelView, model=Post):
    column_list = [Post.id, Post.user_id, Post.content, Post.like_count, Post.is_deleted, Post.created_at]
    column_searchable_list = [Post.content]
    icon = "fa-solid fa-newspaper"
    category = "Content"

class ReportAdmin(ModelView, model=ContentReport):
    column_list = [ContentReport.id, ContentReport.target_type, ContentReport.reason, ContentReport.is_processed]
    icon = "fa-solid fa-flag"
    category = "Moderation"

class SchoolEventAdmin(ModelView, model=SchoolEvent):
    column_list = [SchoolEvent.id, SchoolEvent.title, SchoolEvent.school_name, SchoolEvent.status]
    icon = "fa-solid fa-calendar-days"
    category = "School Life"

# Регистрируем представления в админке
admin.add_view(UserAdmin)
admin.add_view(PostAdmin)
admin.add_view(ReportAdmin)
admin.add_view(SchoolEventAdmin)
# ---------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MEDIA_DIR = "media"
os.makedirs(MEDIA_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")

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

@app.get("/")
def root():
    return {"message": "ClassVibe API is running. Go to /admin for visual dashboard"}