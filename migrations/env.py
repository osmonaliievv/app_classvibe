from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv

# -------------------------------------------------------------------
# Загружаем .env
# -------------------------------------------------------------------
load_dotenv()

# Добавляем путь к проекту, чтобы видеть app/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# -------------------------------------------------------------------
# Импортируем Base и модели
# -------------------------------------------------------------------
from app.database import Base  # noqa
import app.models  # noqa  # просто импортируем модели, чтобы Alembic увидел таблицы

# Алебмиковая конфигурация
config = context.config

# -------------------------------------------------------------------
# Подставляем DATABASE_URL из .env в Alembic
# -------------------------------------------------------------------
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL not found in .env")

config.set_main_option("sqlalchemy.url", database_url)

# Настройка логов Alembic
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Метаданные для автогенерации миграций
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Запуск миграций без подключения к БД"""
    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Запуск миграций при подключении к БД"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,               # сравнение типов колонок
            compare_server_default=True,     # сравнение default значений
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
