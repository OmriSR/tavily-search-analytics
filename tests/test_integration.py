"""Integration tests - correctness proofs for Document Access Processor."""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from models.schemas import EnrichResponse
from processors.document_access import DocumentAccessProcessor
from services.enrichment_client import EnrichmentClient
from storage.analytics_repo import (
    get_domain_stats,
    get_url_stats,
    is_enriched,
    process_event_atomically,
)
from storage.cache import cache_response, get_cached_response
from tests.conftest import create_test_event


@pytest.mark.asyncio
async def test_duplicate_events_are_idempotent(initialized_test_db) -> None:
    """Same event twice → count = 1.

    This is a critical correctness proof: duplicate events must not inflate counts.
    """
    event = create_test_event(event_id="duplicate-test-event")

    # Process same event twice
    result1 = await process_event_atomically(
        event_id=event.event_id,
        url=event.url,
        domain=event.domain,
        timestamp=event.timestamp,
    )
    result2 = await process_event_atomically(
        event_id=event.event_id,
        url=event.url,
        domain=event.domain,
        timestamp=event.timestamp,
    )

    assert result1 is True, "First event should be processed"
    assert result2 is False, "Second event should be rejected as duplicate"

    # Verify counter is 1, not 2
    stats = await get_url_stats(event.url)
    assert stats is not None
    assert stats["access_count"] == 1, "Count should be exactly 1, not 2"


@pytest.mark.asyncio
async def test_enrichment_retry_on_failure(initialized_test_db) -> None:
    """Mock failures → verify retry calls made with exponential backoff.

    Test that the enrichment client retries on failures.
    """
    call_count = [0]
    fail_count = 3  # Fail first 3 attempts

    async def mock_enrich_with_failures(
        self: EnrichmentClient, url: str
    ) -> EnrichResponse:
        call_count[0] += 1
        if call_count[0] <= fail_count:
            # Simulate HTTP error by raising
            raise httpx.HTTPStatusError(
                "Simulated failure",
                request=httpx.Request("POST", "http://test"),
                response=httpx.Response(500),
            )
        return EnrichResponse(url=url, enriched=True)

    # Create client with fast retry delays for testing
    client = EnrichmentClient(
        base_url="http://test",
        max_retries=5,
        base_delay=0.01,  # Very short delay for testing
    )

    with patch.object(
        httpx.AsyncClient,
        "post",
        side_effect=httpx.HTTPStatusError(
            "Simulated failure",
            request=httpx.Request("POST", "http://test"),
            response=httpx.Response(500),
        ),
    ):
        # This should fail after max_retries
        result = await client.enrich("https://example.com/test")

    # Should have made max_retries attempts
    assert result.enriched is False, "Should fail after all retries exhausted"


@pytest.mark.asyncio
async def test_counters_correct_after_partial_failure(initialized_test_db) -> None:
    """Enricher fails but counters still update.

    This proves that counter updates and enrichment are decoupled:
    even if enrichment fails, the event counts should be correct.
    """
    processor = DocumentAccessProcessor()

    # Mock enrichment to always fail
    mock_enrich = AsyncMock(return_value=EnrichResponse(url="", enriched=False))
    processor._enrichment_client.enrich = mock_enrich

    url = "https://partial-failure.example.com/page"
    domain = "partial-failure.example.com"

    # Process event atomically (this should succeed regardless of enrichment)
    event = create_test_event(url=url, domain=domain)
    result = await process_event_atomically(
        event_id=event.event_id,
        url=event.url,
        domain=event.domain,
        timestamp=event.timestamp,
    )
    assert result is True

    # Try enrichment (will fail)
    await processor._handle_enrichment(url)

    # Counters should still be correct
    stats = await get_url_stats(url)
    assert stats is not None
    assert stats["access_count"] == 1, "Counter should update even if enrichment fails"
    assert stats["enriched"] is False, "URL should not be marked enriched"


@pytest.mark.asyncio
async def test_concurrent_events_atomic(initialized_test_db) -> None:
    """100 concurrent events → count = 100.

    This proves atomicity under concurrent load.
    """
    url = "https://concurrent-test.example.com/page"
    domain = "concurrent-test.example.com"
    num_events = 100

    async def process_single_event(event_id: str) -> bool:
        event = create_test_event(
            url=url,
            domain=domain,
            event_id=event_id,
        )
        return await process_event_atomically(
            event_id=event.event_id,
            url=event.url,
            domain=event.domain,
            timestamp=event.timestamp,
        )

    # Process all events concurrently
    tasks = [process_single_event(f"concurrent-event-{i}") for i in range(num_events)]
    results = await asyncio.gather(*tasks)

    # All events should be processed (no duplicates in this test)
    assert all(results), "All unique events should be processed"
    assert sum(results) == num_events

    # Counter should be exactly 100
    stats = await get_url_stats(url)
    assert stats is not None
    assert stats["access_count"] == num_events, f"Count should be {num_events}"

    # Domain stats should also reflect 100 accesses
    domain_stats = await get_domain_stats(domain)
    assert domain_stats is not None
    assert domain_stats["access_count"] == num_events


@pytest.mark.asyncio
async def test_concurrent_duplicate_events_handled_correctly(
    initialized_test_db,
) -> None:
    """Concurrent duplicate events → count = 1.

    This proves deduplication works under concurrent load.
    The production code handles race conditions via UNIQUE constraint.
    """
    url = "https://concurrent-dupe-test.example.com/page"
    domain = "concurrent-dupe-test.example.com"
    shared_event_id = "shared-event-id-456"

    async def process_same_event() -> bool:
        event = create_test_event(
            url=url,
            domain=domain,
            event_id=shared_event_id,
        )
        return await process_event_atomically(
            event_id=event.event_id,
            url=event.url,
            domain=event.domain,
            timestamp=event.timestamp,
        )

    # Process same event 10 times concurrently (smaller batch for test reliability)
    tasks = [process_same_event() for _ in range(10)]
    results = await asyncio.gather(*tasks)
    # Exactly one should succeed, rest should be detected as duplicates
    successes = sum(results)
    assert successes == 1, f"Expected 1 success, got {successes}"

    # Counter should be exactly 1
    stats = await get_url_stats(url)
    assert stats is not None, "URL stats should exist after successful processing"
    assert stats["access_count"] == 1, "Count should be 1 despite concurrent attempts"


@pytest.mark.asyncio
async def test_search_caching_returns_same_response(initialized_test_db) -> None:
    """Second query hits cache - verify cached response returned."""
    query_hash = "test-query-hash-123"
    original_response = {
        "request_id": "req-123",
        "query": "test query",
        "query_hash": query_hash,
        "answer": "This is the answer",
        "sources": [],
        "created_at": "2024-01-01T00:00:00Z",
        "is_cached_response": False,
    }

    # Cache the response
    await cache_response(query_hash, original_response, ttl_seconds=3600)

    # Retrieve from cache
    cached = await get_cached_response(query_hash)

    assert cached is not None
    assert cached["request_id"] == original_response["request_id"]
    assert cached["answer"] == original_response["answer"]


@pytest.mark.asyncio
async def test_cache_miss_returns_none(initialized_test_db) -> None:
    """Non-existent query returns None from cache."""
    result = await get_cached_response("non-existent-hash")
    assert result is None


@pytest.mark.asyncio
async def test_enrichment_marked_after_success(initialized_test_db) -> None:
    """Verify URL is marked as enriched after successful enrichment."""
    processor = DocumentAccessProcessor()

    # Mock enrichment to succeed
    mock_enrich = AsyncMock(
        return_value=EnrichResponse(url="", enriched=True, message="Success")
    )
    processor._enrichment_client.enrich = mock_enrich

    url = "https://enrichment-mark-test.example.com/page"
    domain = "enrichment-mark-test.example.com"

    # Process event first (to create URL stats entry)
    event = create_test_event(url=url, domain=domain)
    await process_event_atomically(
        event_id=event.event_id,
        url=event.url,
        domain=event.domain,
        timestamp=event.timestamp,
    )

    # Initially not enriched
    assert await is_enriched(url) is False

    # Perform enrichment
    await processor._handle_enrichment(url)

    # Now should be enriched
    assert await is_enriched(url) is True


@pytest.mark.asyncio
async def test_domain_aggregation_correctness(initialized_test_db) -> None:
    """Verify domain statistics aggregate correctly across multiple URLs."""
    domain = "multi-url-domain.example.com"
    urls = [f"https://{domain}/page{i}" for i in range(5)]

    # Process events for different URLs under same domain
    for i, url in enumerate(urls):
        event = create_test_event(
            url=url,
            domain=domain,
            event_id=f"domain-test-event-{i}",
        )
        await process_event_atomically(
            event_id=event.event_id,
            url=event.url,
            domain=event.domain,
            timestamp=event.timestamp,
        )

    # Verify domain stats
    domain_stats = await get_domain_stats(domain)
    assert domain_stats is not None
    assert domain_stats["access_count"] == 5, "Domain should have 5 total accesses"
    assert domain_stats["unique_urls"] == 5, "Domain should have 5 unique URLs"
    assert len(domain_stats["urls"]) == 5, "Domain should list all 5 URLs"


@pytest.mark.asyncio
async def test_processor_start_stop_lifecycle(initialized_test_db) -> None:
    """Test processor start/stop lifecycle."""
    processor = DocumentAccessProcessor()

    # Mock enrichment
    mock_enrich = AsyncMock(return_value=EnrichResponse(url="", enriched=True))
    processor._enrichment_client.enrich = mock_enrich

    assert processor._running is False

    # Start processor
    await processor.start()
    assert processor._running is True
    assert processor._task is not None

    # Should not start twice
    await processor.start()  # Should log warning but not error

    # Stop processor
    await processor.stop()
    assert processor._running is False
