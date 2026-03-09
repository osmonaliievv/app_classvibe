from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

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

# ✅ вместо schools.py
from .school_life import router as school_life_router

app = FastAPI(title="ClassVibe API", version="1.0.0")

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
app.include_router(school_life_router)  # ✅
app.include_router(reports_router)
app.include_router(admin_router)

@app.get("/")
def root():
    return {"message": "ClassVibe API is running"}