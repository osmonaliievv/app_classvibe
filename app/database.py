# app/database.py
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# Пытаемся взять готовый DATABASE_URL
database_url = os.getenv("DATABASE_URL")

if not database_url:
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME")

    if not all([DB_USER, DB_PASSWORD, DB_NAME]):
        raise ValueError("Database configuration is not set in .env")

    database_url = (
        f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )

# Создаём движок PostgreSQL
engine = create_engine(
    database_url,
    echo=False,   # можно True, если хочешь видеть SQL-запросы
    future=True,
)

# Сессии
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Базовый класс для моделей
Base = declarative_base()


# Зависимость для FastAPI (как было)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)