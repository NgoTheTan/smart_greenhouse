"""Engine và session SQLAlchemy async dùng chung."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.config import get_settings


class Base(DeclarativeBase):
    """Base cho mọi model ORM (định nghĩa ở core/models.py)."""


engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependency FastAPI: một session cho mỗi request."""
    async with SessionLocal() as session:
        yield session

