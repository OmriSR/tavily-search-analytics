"""Query response caching with TTL expiration."""

import json
import logging
from datetime import UTC, datetime, timedelta

from storage.database import get_database

logger = logging.getLogger(__name__)


async def get_cached_response(query_hash: str) -> dict | None:
    """
    Retrieve cached response if not expired.
    returns None if cache miss or expired.
    """
    db = await get_database()
    now = datetime.now(UTC).isoformat()

    cursor = await db.execute(
        """
        SELECT response_json, expires_at
        FROM query_cache
        WHERE query_hash = ? AND expires_at > ?
        """,
        (query_hash, now),
    )
    row = await cursor.fetchone()

    if row is None:
        logger.debug(f"Cache miss for query {query_hash}")
        return None

    logger.debug(f"Cache hit for query {query_hash}")
    return json.loads(row[0])


async def cache_response(query_hash: str, response: dict, ttl_seconds: int) -> None:
    """
    Store response in cache with TTL expiration
    if query hash already exists 
    """
    db = await get_database()
    expires_at = (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat()
    response_json = json.dumps(response)

    await db.execute(
        """
        INSERT INTO query_cache (query_hash, response_json, expires_at)
        VALUES (?, ?, ?)
        ON CONFLICT(query_hash) DO UPDATE SET
            response_json = ?,
            expires_at = ?
        """,
        (query_hash, response_json, expires_at, response_json, expires_at),
    )
    await db.commit()
    logger.debug(f"Cached response for query {query_hash}, expires at {expires_at}")


async def cleanup_expired() -> int:
    """
    Remove expired cache entries.

    Returns the number of entries removed.
    """
    db = await get_database()
    now = datetime.now(UTC).isoformat()

    cursor = await db.execute(
        "SELECT COUNT(*) FROM query_cache WHERE expires_at <= ?",
        (now,),
    )
    count = (await cursor.fetchone())[0]

    if count > 0:
        await db.execute(
            "DELETE FROM query_cache WHERE expires_at <= ?",
            (now,),
        )
        await db.commit()
        logger.info(f"Cleaned up {count} expired cache entries")

    return count
