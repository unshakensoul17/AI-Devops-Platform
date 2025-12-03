# backend/database/connection.py

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from config.settings import get_settings
from sqlalchemy import text
import logging
import re

logger = logging.getLogger(__name__)
settings = get_settings()

# -------------------------------------------------------------------
# FIX: Convert sync Postgres URL → asyncpg URL
# -------------------------------------------------------------------
database_url = settings.DATABASE_URL

# Render gives postgres:// which is deprecated → fix that
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

# Convert sync driver → asyncpg driver
# postgresql:// → postgresql+asyncpg://
if database_url.startswith("postgresql://") and "+asyncpg" not in database_url:
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

logger.info(f"Using database URL: {database_url}")
# -------------------------------------------------------------------

# Create async engine
engine = create_async_engine(
    database_url,
    poolclass=NullPool,  # Required for Render free tier
    echo=settings.DEBUG,
)

# Async session factory
async_session_maker = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession
)

async def get_db():
    """FastAPI dependency to get DB session"""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Create extensions + tables"""
    from database.models import Base
    
    async with engine.begin() as conn:
        # Enable pg_trgm for search
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

        # Create tables
        await conn.run_sync(Base.metadata.create_all)

    logger.info("✅ Database initialized")
