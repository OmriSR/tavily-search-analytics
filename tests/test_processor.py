"""Unit tests for Document Access Processor."""

from unittest.mock import AsyncMock

import pytest

from core.document_access_processor import DocumentAccessProcessor
from core.models.events import DocumentAccessEvent
from core.models.schemas import EnrichResponse
from data.analytics_repo import get_url_stats, is_enriched, process_event_atomically
from tests.conftest import create_test_event


@pytest.mark.asyncio
async def test_deduplication_same_event_id_processed_once(initialized_test_db) -> None:
    """Verify duplicate events with same event_id are skipped."""
    event_id = "unique-event-123"
    event = create_test_event(event_id=event_id)

    # Process the same event twice
    first_result = await process_event_atomically(
        event_id=event.event_id,
        url=event.url,
        url_hash=event.url_hash,
        domain=event.domain,
        timestamp=event.timestamp,
    )
    second_result = await process_event_atomically(
        event_id=event.event_id,
        url=event.url,
        url_hash=event.url_hash,
        domain=event.domain,
        timestamp=event.timestamp,
    )

    # First should succeed, second should be duplicate
    assert first_result is True
    assert second_result is False

    # Verify URL count is 1, not 2
    stats = await get_url_stats(event.url_hash)
    assert stats is not None
    assert stats["access_count"] == 1


@pytest.mark.asyncio
async def test_url_counter_increments_correctly(initialized_test_db) -> None:
    """Verify access count increases for each unique event."""
    url = "https://example.com/test-page"
    domain = "example.com"

    # Create one event to get the url_hash
    sample_event = create_test_event(url=url, domain=domain)
    url_hash = sample_event.url_hash

    # Process 3 events with different event_ids but same URL
    for i in range(3):
        event = create_test_event(
            url=url,
            domain=domain,
            event_id=f"event-{i}",
        )
        await process_event_atomically(
            event_id=event.event_id,
            url=event.url,
            url_hash=event.url_hash,
            domain=event.domain,
            timestamp=event.timestamp,
        )

    stats = await get_url_stats(url_hash)
    assert stats is not None
    assert stats["access_count"] == 3


@pytest.mark.asyncio
async def test_domain_extraction_preserves_subdomain(initialized_test_db) -> None:
    """Verify full subdomain (e.g., api.example.com) is preserved, not just root domain."""
    # Test with subdomain
    url = "https://api.docs.example.com/v1/page"
    domain = "api.docs.example.com"  # Full subdomain, not just example.com

    event = create_test_event(
        url=url,
        domain=domain,
    )
    await process_event_atomically(
        event_id=event.event_id,
        url=event.url,
        url_hash=event.url_hash,
        domain=event.domain,
        timestamp=event.timestamp,
    )

    stats = await get_url_stats(event.url_hash)
    assert stats is not None
    assert stats["domain"] == "api.docs.example.com"


@pytest.mark.asyncio
async def test_enrichment_called_for_new_urls(initialized_test_db) -> None:
    """Verify enricher is invoked for newly seen URLs."""
    processor = DocumentAccessProcessor()

    # Mock the enrichment client
    mock_enrich = AsyncMock(return_value=EnrichResponse(url="", enriched=True))
    processor._enrichment_client.enrich = mock_enrich

    event = create_test_event(
        url="https://new-url.example.com/page",
        domain="new-url.example.com",
    )

    # Process event
    await process_event_atomically(
        event_id=event.event_id,
        url=event.url,
        url_hash=event.url_hash,
        domain=event.domain,
        timestamp=event.timestamp,
    )

    # Handle enrichment
    await processor._handle_enrichment(event.url)

    # Enricher should be called
    mock_enrich.assert_called_once_with(event.url)


@pytest.mark.asyncio
async def test_enrichment_not_called_for_already_enriched(initialized_test_db) -> None:
    """Verify no duplicate enrichment calls for already-enriched URLs."""
    processor = DocumentAccessProcessor()

    # Mock the enrichment client
    mock_enrich = AsyncMock(return_value=EnrichResponse(url="", enriched=True))
    processor._enrichment_client.enrich = mock_enrich

    url = "https://already-enriched.example.com/page"
    domain = "already-enriched.example.com"

    # First event - should trigger enrichment
    event1 = create_test_event(
        url=url,
        domain=domain,
        event_id="first-event",
    )
    await process_event_atomically(
        event_id=event1.event_id,
        url=event1.url,
        url_hash=event1.url_hash,
        domain=event1.domain,
        timestamp=event1.timestamp,
    )
    await processor._handle_enrichment(url)

    # Verify enriched
    assert await is_enriched(url) is True

    # Reset mock to track new calls
    mock_enrich.reset_mock()

    # Second event for same URL - should NOT call enricher again
    event2 = create_test_event(
        url=url,
        domain=domain,
        event_id="second-event",
    )
    await process_event_atomically(
        event_id=event2.event_id,
        url=event2.url,
        url_hash=event2.url_hash,
        domain=event2.domain,
        timestamp=event2.timestamp,
    )
    await processor._handle_enrichment(url)

    # Enricher should NOT be called (already enriched)
    mock_enrich.assert_not_called()


@pytest.mark.asyncio
async def test_processor_enqueue_and_process(initialized_test_db) -> None:
    """Test that processor correctly enqueues and processes events."""
    processor = DocumentAccessProcessor()

    # Mock enrichment client
    mock_enrich = AsyncMock(return_value=EnrichResponse(url="", enriched=True))
    processor._enrichment_client.enrich = mock_enrich

    event = create_test_event()

    # Enqueue event
    await processor.enqueue(event)

    # Verify event is in queue
    assert processor._queue.qsize() == 1

    # Start processor, let it process, then stop
    await processor.start()

    # Give processor time to process the event
    import asyncio

    await asyncio.sleep(0.5)

    await processor.stop()

    # Queue should be empty after processing
    assert processor._queue.qsize() == 0


@pytest.mark.asyncio
async def test_event_validation_rejects_empty_url() -> None:
    """Verify event validation rejects empty URL."""
    with pytest.raises(ValueError, match="URL cannot be empty"):
        DocumentAccessEvent(
            url="",
            url_hash="somehash",
            domain="example.com",
            query_hash="hash123",
            request_id="req123",
        )


@pytest.mark.asyncio
async def test_event_validation_rejects_empty_domain() -> None:
    """Verify event validation rejects empty domain."""
    with pytest.raises(ValueError, match="Domain cannot be empty"):
        DocumentAccessEvent(
            url="https://example.com",
            url_hash="somehash",
            domain="",
            query_hash="hash123",
            request_id="req123",
        )


@pytest.mark.asyncio
async def test_processor_graceful_shutdown(initialized_test_db) -> None:
    """Test that processor drains queue on shutdown."""
    processor = DocumentAccessProcessor()

    # Mock enrichment
    mock_enrich = AsyncMock(return_value=EnrichResponse(url="", enriched=True))
    processor._enrichment_client.enrich = mock_enrich

    # Start the processor first (drain only happens if processor was running)
    await processor.start()

    # Enqueue multiple events
    for i in range(5):
        event = create_test_event(
            url=f"https://example.com/page{i}",
            event_id=f"shutdown-event-{i}",
        )
        await processor.enqueue(event)

    # Give the processor a moment to potentially start processing
    import asyncio

    await asyncio.sleep(0.1)

    # Stop should drain remaining events
    await processor.stop()

    # Queue should be empty after shutdown drains it
    assert processor._queue.qsize() == 0
