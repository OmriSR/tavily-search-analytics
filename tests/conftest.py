"""Pytest fixtures for isolated testing."""

import tempfile
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from api.search import compute_url_hash
from core.document_access_processor import DocumentAccessProcessor
from core.models.events import DocumentAccessEvent
from core.models.schemas import EnrichResponse
from core.services.enrichment_client import EnrichmentClient


async def create_schema(db: aiosqlite.Connection) -> None:
    """Create all required tables in the database."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_events (
            event_id TEXT PRIMARY KEY,
            processed_at TEXT NOT NULL
        )
    """
    )

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS url_stats (
            url TEXT PRIMARY KEY,
            url_hash TEXT NOT NULL,
            domain TEXT NOT NULL,
            access_count INTEGER NOT NULL DEFAULT 0,
            first_accessed TEXT NOT NULL,
            last_accessed TEXT NOT NULL,
            enriched INTEGER NOT NULL DEFAULT 0
        )
    """
    )

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

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS query_urls (
            query_hash TEXT NOT NULL,
            url TEXT NOT NULL,
            PRIMARY KEY (query_hash, url)
        )
    """
    )

    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_url_stats_domain ON url_stats(domain)"
    )
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_url_stats_url_hash ON url_stats(url_hash)"
    )

    await db.commit()


@pytest_asyncio.fixture
async def test_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """In-memory SQLite database for isolated testing."""
    db = await aiosqlite.connect(":memory:")
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
    await create_schema(db)
    yield db
    await db.close()


@pytest.fixture
def mock_db_connection(test_db: aiosqlite.Connection) -> Generator[None, None, None]:
    """Patch database connection to use test database."""

    @asynccontextmanager
    async def get_test_db_connection() -> AsyncGenerator[aiosqlite.Connection, None]:
        yield test_db

    with (patch("data.database.get_database_connection", get_test_db_connection),):
        yield


@pytest_asyncio.fixture
async def initialized_test_db() -> AsyncGenerator[Path, None]:
    """Test database with patched get_database_connection function.

    Uses a temp file database so multiple connections can access the same data,
    which better imitates real production behavior.
    """
    # Create a temp file for the database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    # Initialize the schema
    init_db = await aiosqlite.connect(db_path)
    await init_db.execute("PRAGMA journal_mode=WAL")
    await init_db.execute("PRAGMA synchronous=NORMAL")
    await create_schema(init_db)
    await init_db.close()

    @asynccontextmanager
    async def get_test_db_connection() -> AsyncGenerator[aiosqlite.Connection, None]:
        """Each caller gets their own connection to the shared database file."""
        async with aiosqlite.connect(db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=NORMAL")
            yield db

    with (
        patch("data.database.get_database_connection", get_test_db_connection),
        patch("data.analytics_repo.get_database_connection", get_test_db_connection),
    ):
        yield db_path

    # Cleanup temp file
    db_path.unlink(missing_ok=True)
    # Also cleanup WAL and SHM files if they exist
    Path(f"{db_path}-wal").unlink(missing_ok=True)
    Path(f"{db_path}-shm").unlink(missing_ok=True)


@pytest.fixture
def mock_enricher_success() -> Generator[AsyncMock, None, None]:
    """Mock enricher that always succeeds."""
    mock = AsyncMock(return_value=EnrichResponse(url="", enriched=True))
    with patch.object(EnrichmentClient, "enrich", mock):
        yield mock


@pytest.fixture
def mock_enricher_failure() -> Generator[AsyncMock, None, None]:
    """Mock enricher that always fails."""
    mock = AsyncMock(return_value=EnrichResponse(url="", enriched=False))
    with patch.object(EnrichmentClient, "enrich", mock):
        yield mock


def create_mock_enricher_with_failures(
    fail_count: int,
) -> tuple[AsyncMock, list[int]]:
    """Create a mock enricher that fails a specific number of times then succeeds.

    Args:
        fail_count: Number of times to fail before succeeding

    Returns:
        Tuple of (mock, call_counter) where call_counter tracks call count
    """
    call_counter = [0]

    async def enrich_with_failures(url: str) -> EnrichResponse:
        call_counter[0] += 1
        if call_counter[0] <= fail_count:
            return EnrichResponse(url=url, enriched=False)
        return EnrichResponse(url=url, enriched=True)

    mock = AsyncMock(side_effect=enrich_with_failures)
    return mock, call_counter


@pytest_asyncio.fixture
async def processor_with_test_db(
    initialized_test_db: Path,
) -> AsyncGenerator[DocumentAccessProcessor, None]:
    """Document Access Processor with test database and mock enricher."""
    processor = DocumentAccessProcessor()

    # Mock the enrichment client to always succeed
    mock_enricher = AsyncMock(return_value=EnrichResponse(url="", enriched=True))
    processor._enrichment_client.enrich = mock_enricher

    yield processor


def create_test_event(
    url: str = "https://example.com/test",
    domain: str = "example.com",
    query_hash: str = "testhash123",
    request_id: str = "request123",
    event_id: str | None = None,
) -> DocumentAccessEvent:
    """Factory function to create test events."""
    url_hash = compute_url_hash(url)
    kwargs: dict[str, Any] = {
        "url": url,
        "url_hash": url_hash,
        "domain": domain,
        "query_hash": query_hash,
        "request_id": request_id,
    }
    if event_id is not None:
        kwargs["event_id"] = event_id
    return DocumentAccessEvent(**kwargs)


@pytest.fixture
def test_client() -> Generator[TestClient, None, None]:
    """FastAPI TestClient with mocked dependencies."""
    from main import app

    with TestClient(app) as client:
        yield client


@pytest_asyncio.fixture
async def async_test_client() -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for testing FastAPI endpoints."""
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
def mock_tavily_response() -> dict[str, Any]:
    """Mock Tavily API response."""
    return {
        "request_id": "test-request-id",
        "answer": "This is the answer from Tavily",
        "response_time_ms": 150.0,
        "results": [
            {
                "url": "https://docs.example.com/page1",
                "title": "Example Documentation",
                "content": "This is the content of the first result.",
            },
            {
                "url": "https://api.example.com/docs",
                "title": "API Documentation",
                "content": "This is the content of the second result.",
            },
        ],
    }


@pytest.fixture
def mock_llm_answer() -> str:
    """Mock LLM-generated answer."""
    return "This is the enhanced answer from the LLM service."
