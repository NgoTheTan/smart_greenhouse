"""Engine và session SQLAlchemy async dùng chung (PostgreSQL chính; Dev SQLite tách biệt)."""

import logging
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.config import get_settings

log = logging.getLogger("core.db")


class Base(DeclarativeBase):
    """Base cho mọi model ORM (định nghĩa ở core/models.py)."""


_REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_DB_FILE = _REPO_ROOT / "greenhub_dev.sqlite3"
DEV_SQLITE_URL = f"sqlite+aiosqlite:///{DEV_DB_FILE.as_posix()}"

_settings = get_settings()
is_dev_sqlite = bool(_settings.use_dev_sqlite or _settings.database_url.startswith("sqlite"))

if is_dev_sqlite:
    effective_database_url = (
        _settings.database_url
        if _settings.database_url.startswith("sqlite")
        else DEV_SQLITE_URL
    )
    log.info("Đang chạy chế độ Dev SQLite (USE_DEV_SQLITE): %s", effective_database_url)
else:
    effective_database_url = _settings.database_url

engine = create_async_engine(effective_database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
_dev_db_initialized = False


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependency FastAPI: một session cho mỗi request."""
    global _dev_db_initialized
    if is_dev_sqlite and not _dev_db_initialized:
        from core.dev_db import init_dev_database

        await init_dev_database(engine)
        _dev_db_initialized = True

    async with SessionLocal() as session:
        yield session
