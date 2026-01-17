"""SQLite database connection and schema management."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import aiosqlite

from config import settings

logger = logging.getLogger(__name__)


async def init_database() -> None:
    """initialize database with schemas and close connection"""
    async with aiosqlite.connect(settings.database_path) as db:
        await _create_schema(db)
        await db.commit()


@asynccontextmanager
async def get_database_connection() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Get the database connection - for each request a separate connection."""
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        yield db


async def _create_schema(db: aiosqlite.Connection) -> None:
    """Create all database tables."""
    # Processed events table for idempotency
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_events (
            event_id TEXT PRIMARY KEY,
            processed_at TEXT NOT NULL
        )
    """
    )

    # URL statistics table
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS url_stats (
            url TEXT PRIMARY KEY,
            domain TEXT NOT NULL,
            access_count INTEGER NOT NULL DEFAULT 0,
            first_accessed TEXT NOT NULL,
            last_accessed TEXT NOT NULL,
            enriched INTEGER NOT NULL DEFAULT 0
        )
    """
    )

    # Domain statistics table
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS domain_stats (
            domain TEXT PRIMARY KEY,
            access_count INTEGER NOT NULL DEFAULT 0,
            unique_urls INTEGER NOT NULL DEFAULT 0,
            first_accessed TEXT NOT NULL,
            last_accessed TEXT NOT NULL
        )
    """
    )

    # Query statistics table
    await db.execute(
        """
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
    """
    )

    # Query-URL mapping table for tracking which URLs were accessed for each query
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS query_urls (
            query_hash TEXT NOT NULL,
            url TEXT NOT NULL,
            PRIMARY KEY (query_hash, url),
            FOREIGN KEY (query_hash) REFERENCES query_stats(query_hash),
            FOREIGN KEY (url) REFERENCES url_stats(url)
        )
    """
    )

    # Create indexes for common queries
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_url_stats_domain ON url_stats(domain)"
    )


@asynccontextmanager
async def transaction() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Context manager for database transactions."""
    async with get_database_connection() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise
