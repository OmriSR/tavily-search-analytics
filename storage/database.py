"""SQLite database connection and schema management."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import aiosqlite

from config import settings

logger = logging.getLogger(__name__)

# Global database connection
_db: aiosqlite.Connection | None = None


async def get_database() -> aiosqlite.Connection:
    """Get the database connection, initializing if needed."""
    global _db
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _db


async def init_database() -> None:
    """Initialize the database connection and create schema."""
    global _db
    _db = await aiosqlite.connect(settings.database_path)

    # Enable WAL mode for better concurrent read/write performance
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA synchronous=NORMAL")

    # Create tables
    await _create_schema(_db)
    await _db.commit()
    logger.info("Database schema initialized")


async def close_database() -> None:
    """Close the database connection."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("Database connection closed")


async def _create_schema(db: aiosqlite.Connection) -> None:
    """Create all database tables."""
    # Processed events table for idempotency
    await db.execute("""
        CREATE TABLE IF NOT EXISTS processed_events (
            event_id TEXT PRIMARY KEY,
            processed_at TEXT NOT NULL
        )
    """)

    # URL statistics table
    await db.execute("""
        CREATE TABLE IF NOT EXISTS url_stats (
            url TEXT PRIMARY KEY,
            domain TEXT NOT NULL,
            access_count INTEGER NOT NULL DEFAULT 0,
            first_accessed TEXT NOT NULL,
            last_accessed TEXT NOT NULL,
            enriched INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Domain statistics table
    await db.execute("""
        CREATE TABLE IF NOT EXISTS domain_stats (
            domain TEXT PRIMARY KEY,
            access_count INTEGER NOT NULL DEFAULT 0,
            unique_urls INTEGER NOT NULL DEFAULT 0,
            first_accessed TEXT NOT NULL,
            last_accessed TEXT NOT NULL
        )
    """)

    # Query cache table
    await db.execute("""
        CREATE TABLE IF NOT EXISTS query_cache (
            query_hash TEXT PRIMARY KEY,
            response_json TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    """)

    # Query statistics table
    await db.execute("""
        CREATE TABLE IF NOT EXISTS query_stats (
            query_hash TEXT PRIMARY KEY,
            query_text TEXT NOT NULL,
            total_requests INTEGER NOT NULL DEFAULT 0,
            successful_requests INTEGER NOT NULL DEFAULT 0,
            failed_requests INTEGER NOT NULL DEFAULT 0,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            avg_response_time_ms REAL NOT NULL DEFAULT 0.0
        )
    """)

    # Query-URL mapping table for tracking which URLs were accessed for each query
    await db.execute("""
        CREATE TABLE IF NOT EXISTS query_urls (
            query_hash TEXT NOT NULL,
            url TEXT NOT NULL,
            PRIMARY KEY (query_hash, url),
            FOREIGN KEY (query_hash) REFERENCES query_stats(query_hash),
            FOREIGN KEY (url) REFERENCES url_stats(url)
        )
    """)

    # Create indexes for common queries
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_url_stats_domain ON url_stats(domain)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_query_cache_expires ON query_cache(expires_at)"
    )


@asynccontextmanager
async def transaction() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Context manager for database transactions."""
    db = await get_database()
    try:
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise
