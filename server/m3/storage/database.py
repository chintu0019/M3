"""
M3 Database — Async SQLAlchemy engine and session management.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from m3.config import DatabaseSettings


async def init_db(settings: DatabaseSettings) -> tuple:
    """Create the async engine and session factory.

    Returns (engine, session_factory) tuple.
    """
    engine = create_async_engine(
        settings.url,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        echo=False,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory


async def get_session(session_factory: async_sessionmaker) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
