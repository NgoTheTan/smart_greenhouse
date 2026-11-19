"""Engine và session SQLAlchemy async dùng chung (hỗ trợ tự động fallback sang Dev SQLite khi không có Docker)."""

import logging
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.config import get_settings

log = logging.getLogger("core.db")


class Base(DeclarativeBase):
    """Base cho mọi model ORM (định nghĩa ở core/models.py)."""


def _is_postgres_available(url: str, timeout: float = 0.5) -> bool:
    """Kiểm tra nhanh cổng PostgreSQL trước khi kết nối."""
    if not url.startswith("postgresql"):
        return False
    try:
        p = urlparse(url)
        host = p.hostname or "localhost"
        port = p.port or 5432
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.error, OSError):
        return False


_REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_DB_FILE = _REPO_ROOT / "greenhub_dev.sqlite3"
DEV_SQLITE_URL = f"sqlite+aiosqlite:///{DEV_DB_FILE.as_posix()}"

_settings = get_settings()
_pg_ok = _is_postgres_available(_settings.database_url)

if _pg_ok:
    log.info("Kết nối tới PostgreSQL: %s", _settings.database_url)
    effective_database_url = _settings.database_url
    engine = create_async_engine(effective_database_url, pool_pre_ping=True)
else:
    log.info(
        "PostgreSQL không khả dụng trên localhost:5432. Tự động chuyển sang Dev SQLite: %s",
        DEV_SQLITE_URL,
    )
    effective_database_url = DEV_SQLITE_URL
    engine = create_async_engine(DEV_SQLITE_URL, pool_pre_ping=True)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
_dev_db_initialized = False


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependency FastAPI: một session cho mỗi request."""
    global _dev_db_initialized
    if not _pg_ok and not _dev_db_initialized:
        from core.dev_db import init_dev_database

        await init_dev_database(engine)
        _dev_db_initialized = True

    async with SessionLocal() as session:
        yield session
