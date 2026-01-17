import logging
from datetime import UTC, datetime

import aiosqlite

from data.database import get_database_connection, transaction

logger = logging.getLogger(__name__)


async def is_duplicate(event_id: str, db: aiosqlite.Connection) -> bool:
    """Check if an event has already been processed."""
    cursor = await db.execute(
        "SELECT 1 FROM processed_events WHERE event_id = ?",
        (event_id,),
    )
    row = await cursor.fetchone()
    return row is not None


async def mark_processed(event_id: str, db: aiosqlite.Connection) -> None:
    """Mark an event as processed (within a transaction)."""
    timestamp = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO processed_events (event_id, processed_at) VALUES (?, ?)",
        (event_id, timestamp),
    )


async def increment_url_count(
    url: str, domain: str, timestamp: str, db: aiosqlite.Connection
) -> None:
    """Increment URL access count (upsert operation)."""
    await db.execute(
        """
        INSERT INTO url_stats (url, domain, access_count, first_accessed, last_accessed, enriched)
        VALUES (?, ?, 1, ?, ?, 0)
        ON CONFLICT(url) DO UPDATE SET
            access_count = access_count + 1,
            last_accessed = ?
        """,
        (url, domain, timestamp, timestamp, timestamp),
    )


async def increment_domain_count(
    domain: str, url: str, timestamp: str, db: aiosqlite.Connection
) -> None:
    """Increment domain access count and unique URL count."""
    # Check if this URL is new for the domain
    cursor = await db.execute(
        "SELECT 1 FROM url_stats WHERE url = ? AND access_count = 1",
        (url,),
    )
    is_new_url = await cursor.fetchone() is not None

    # If new URL, increment unique_urls; always increment access_count
    if is_new_url:
        await db.execute(
            """
            INSERT INTO domain_stats (domain, access_count, unique_urls, first_accessed, last_accessed)
            VALUES (?, 1, 1, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET
                access_count = access_count + 1,
                unique_urls = unique_urls + 1,
                last_accessed = ?
            """,
            (domain, timestamp, timestamp, timestamp),
        )
    else:
        await db.execute(
            """
            INSERT INTO domain_stats (domain, access_count, unique_urls, first_accessed, last_accessed)
            VALUES (?, 1, 1, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET
                access_count = access_count + 1,
                last_accessed = ?
            """,
            (domain, timestamp, timestamp, timestamp),
        )


async def update_query_stats(
    query_hash: str,
    query_text: str,
    response_time_ms: float,
    success: bool,
    urls: list[str],
) -> None:
    """Update query statistics (upsert operation)."""
    async with get_database_connection() as db:
        timestamp = datetime.now(UTC).isoformat()

        # Get existing stats for rolling average calculation
        cursor = await db.execute(
            "SELECT total_requests, avg_response_time_ms FROM query_stats WHERE query_hash = ?",
            (query_hash,),
        )
        row = await cursor.fetchone()

        if row:
            old_total, old_avg = row
            new_total = old_total + 1
            # Calculate new rolling average
            new_avg = ((old_avg * old_total) + response_time_ms) / new_total
        else:
            new_total = 1
            new_avg = response_time_ms

        success_increment = 1 if success else 0
        failed_increment = 0 if success else 1

        await db.execute(
            """
            INSERT INTO query_stats (
                query_hash, query_text, total_requests, successful_requests,
                failed_requests, first_seen, last_seen, avg_response_time_ms
            )
            VALUES (?, ?, 1, ?, ?, ?, ?, ?)
            ON CONFLICT(query_hash) DO UPDATE SET
                total_requests = total_requests + 1,
                successful_requests = successful_requests + ?,
                failed_requests = failed_requests + ?,
                last_seen = ?,
                avg_response_time_ms = ?
            """,
            (
                query_hash,
                query_text,
                success_increment,
                failed_increment,
                timestamp,
                timestamp,
                new_avg,
                success_increment,
                failed_increment,
                timestamp,
                new_avg,
            ),
        )

        # Track URLs associated with this query
        for url in urls:
            await db.execute(
                """
                INSERT OR IGNORE INTO query_urls (query_hash, url)
                VALUES (?, ?)
                """,
                (query_hash, url),
            )

        await db.commit()


async def get_url_stats(url: str) -> dict | None:
    """Retrieve URL analytics."""
    async with get_database_connection() as db:
        cursor = await db.execute(
            """
            SELECT url, domain, access_count, first_accessed, last_accessed, enriched
            FROM url_stats
            WHERE url = ?
            """,
            (url,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        return {
            "url": row[0],
            "domain": row[1],
            "access_count": row[2],
            "first_accessed": row[3],
            "last_accessed": row[4],
            "enriched": bool(row[5]),
        }


async def get_domain_stats(domain: str) -> dict | None:
    """Retrieve domain analytics."""
    async with get_database_connection() as db:
        cursor = await db.execute(
            """
            SELECT domain, access_count, unique_urls, first_accessed, last_accessed
            FROM domain_stats
            WHERE domain = ?
            """,
            (domain,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        # Get all URLs for this domain
        url_cursor = await db.execute(
            "SELECT url FROM url_stats WHERE domain = ?",
            (domain,),
        )
        urls = [r[0] for r in await url_cursor.fetchall()]

        return {
            "domain": row[0],
            "access_count": row[1],
            "unique_urls": row[2],
            "first_accessed": row[3],
            "last_accessed": row[4],
            "urls": urls,
        }


async def get_query_stats(query_hash: str) -> dict | None:
    """Retrieve query analytics."""
    async with get_database_connection() as db:
        cursor = await db.execute(
            """
            SELECT query_hash, query_text, total_requests, successful_requests,
                   failed_requests, first_seen, last_seen, avg_response_time_ms
            FROM query_stats
            WHERE query_hash = ?
            """,
            (query_hash,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        # Get URLs associated with this query
        url_cursor = await db.execute(
            "SELECT url FROM query_urls WHERE query_hash = ?",
            (query_hash,),
        )
        urls = [r[0] for r in await url_cursor.fetchall()]

        return {
            "query_hash": row[0],  # add for testing
            "query": row[1],
            "total_requests": row[2],
            "successful_requests": row[3],
            "failed_requests": row[4],
            "first_seen": row[5],
            "last_seen": row[6],
            "avg_response_time_ms": row[7],
            "urls": urls,
        }


async def is_enriched(url: str) -> bool:
    """Check if a URL has been enriched."""
    async with get_database_connection() as db:
        cursor = await db.execute(
            "SELECT enriched FROM url_stats WHERE url = ?",
            (url,),
        )
        row = await cursor.fetchone()
        return row is not None and bool(row[0])


async def mark_enriched(url: str) -> None:
    """Mark a URL as enriched."""
    async with get_database_connection() as db:
        await db.execute(
            "UPDATE url_stats SET enriched = 1 WHERE url = ?",
            (url,),
        )
        await db.commit()


async def process_event_atomically(
    event_id: str,
    url: str,
    domain: str,
    timestamp: str,
) -> bool:
    """
    Process an event atomically: check duplicate, mark processed, update counters

    It works as 'All Or Nothing' - if crash or shutdown mid transaction, all writes to the DB are deleted.
    By that we insure that an event will be marked as processed only if it was completed

    Returns True if event was processed, False if duplicate.

    Note: Handles race conditions where concurrent events pass the is_duplicate check
    but then one fails on insert due to UNIQUE constraint - this is treated as a duplicate.
    """
    from sqlite3 import IntegrityError

    try:
        async with transaction() as db:
            # early return (duplicate events correctness)
            if await is_duplicate(event_id, db):
                logger.debug(f"Duplicate event {event_id}, skipping")
                return False

            await mark_processed(event_id, db)
            await increment_url_count(url, domain, timestamp, db)
            await increment_domain_count(domain, url, timestamp, db)

            logger.debug(f"Processed event {event_id} for URL {url}")
            return True
    except IntegrityError:
        # possible race condition: 2+ coroutines check dups for a given event -> both return false
        # (neither marked as processed yet) -> one of them marks the event as processed first ->
        # the second gets integrity error when trying
        # this is a deduplication enforcement (duplicate events correctness)
        logger.debug(f"Duplicate event {event_id} detected via constraint, skipping")
        return False
