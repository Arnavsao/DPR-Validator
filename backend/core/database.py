"""
Async SQLAlchemy database engine and session factory.
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from core.config import settings
import logging

logger = logging.getLogger(__name__)

# Ensure parent dir exists for SQLite
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)

from sqlalchemy import event

@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in settings.DATABASE_URL:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        except Exception as e:
            logger.warning(f"Failed to set SQLite pragmas: {e}")
        finally:
            cursor.close()

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

class Base(DeclarativeBase):
    pass


async def init_db():
    """Create all tables on startup."""
    from models import db_models  # noqa: F401 — ensures models are registered
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
        # Check and migrate new columns in documents table
        new_cols = [
            ("documents", "is_paused", "BOOLEAN", "0"),
            ("documents", "progress_percent", "INTEGER", "0"),
            ("documents", "current_stage", "TEXT", "NULL"),
            ("documents", "estimated_remaining_seconds", "INTEGER", "0"),
        ]
        for table, column, col_type, default in new_cols:
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            columns = [row[1] for row in result.fetchall()]
            if column not in columns:
                sql = f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT {default}"
                await conn.execute(text(sql))
                logger.info(f"Database Migration: Added column {column} ({col_type}) to {table} table.")
    logger.info("Database tables initialized.")


async def get_db():
    """FastAPI dependency for DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
