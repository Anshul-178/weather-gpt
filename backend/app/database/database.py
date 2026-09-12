"""Database engine and session management (SQLAlchemy async)."""

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine, expire_on_commit=False, autoflush=False
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a database session."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create tables on startup (migrations own the schema in production)."""
    from app.database.base import Base  # noqa: F401 - ensure metadata loaded
    import app.models.user  # noqa: F401
    import app.models.location  # noqa: F401
    import app.models.alert  # noqa: F401
    import app.models.chat  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized")


async def dispose_db() -> None:
    """Dispose engine connections on shutdown."""
    await engine.dispose()
