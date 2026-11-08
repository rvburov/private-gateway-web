from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


@lru_cache
def get_engine():
    return create_async_engine(
        get_settings().database_url, pool_pre_ping=True, pool_size=5, max_overflow=5
    )


@lru_cache
def get_session_factory():
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
