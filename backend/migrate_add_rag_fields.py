"""
migrate_add_rag_fields.py — Safe migration to add RAG fields to existing DB.

Run ONCE if you have an existing database:
    python migrate_add_rag_fields.py

Safe: uses ALTER TABLE with column existence check.
For fresh installs, SQLAlchemy's create_all handles this automatically.
"""
import asyncio
import logging
import sys
from pathlib import Path

# Bootstrap path
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from sqlalchemy import text
from core.database import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
logger = logging.getLogger(__name__)


NEW_COLUMNS = [
    # (table, column, sql_type, default)
    ("findings", "reference_section",    "TEXT", "NULL"),
    ("findings", "evidence",             "TEXT", "NULL"),
    ("findings", "suggested_correction", "TEXT", "NULL"),
    ("validation_runs", "validation_mode", "VARCHAR(16)", "'heuristic'"),
]


async def migrate():
    async with engine.begin() as conn:
        for table, column, col_type, default in NEW_COLUMNS:
            # Check if column already exists (SQLite-compatible)
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            columns = [row[1] for row in result.fetchall()]

            if column in columns:
                logger.info(f"  ✓ {table}.{column} already exists — skipping.")
            else:
                sql = f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT {default}"
                await conn.execute(text(sql))
                logger.info(f"  + Added {table}.{column} ({col_type})")

    logger.info("Migration complete.")


if __name__ == "__main__":
    logger.info("Running RAG fields migration...")
    asyncio.run(migrate())
