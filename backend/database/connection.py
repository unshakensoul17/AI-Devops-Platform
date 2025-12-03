# backend/database/connection.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from config.settings import get_settings
import logging

logger = logging.getLogger(__name__)
settings = get_settings()

# Convert postgres:// to postgresql:// for SQLAlchemy
database_url = settings.DATABASE_URL
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

# Create async engine
engine = create_async_engine(
    database_url,
    poolclass=NullPool,  # Important for Render Free tier
    echo=settings.DEBUG,
)

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db():
    """Dependency for getting database sessions"""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()

async def init_db():
    """Initialize database and create tables"""
    from database.models import Base
    
    async with engine.begin() as conn:
        # Enable pg_trgm extension for full-text search
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
    
    logger.info("✅ Database initialized")