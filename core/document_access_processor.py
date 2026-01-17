import asyncio
import contextlib
import logging
from asyncio import Queue, Task

from core.models.events import DocumentAccessEvent
from core.services.enrichment_client import EnrichmentClient
from data.analytics_repo import (
    is_enriched,
    mark_enriched,
    process_event_atomically,
)

logger = logging.getLogger(__name__)


class DocumentAccessProcessor:
    """Async event processor for document access tracking.

    Key responsibilities:
    1. Event deduplication by event_id (UUID)
    2. Atomic counter updates (within transaction)
    3. Enrichment with exponential backoff retry
    4. Graceful shutdown with queue draining
    """

    def __init__(self) -> None:
        self._queue: Queue[DocumentAccessEvent] = Queue()
        self._task: Task[None] | None = None
        self._running: bool = False
        self._enrichment_client = EnrichmentClient()

    async def start(self) -> None:
        """Start the processor's process loop background task"""
        if self._running:
            logger.warning("Processor already running")
            return

        self._running = True
        self._task = asyncio.create_task(
            self._process_loop()
        )  # add the DAP to the main event loop so it can run "between" API calls
        logger.info("Document Access Processor started")

    async def stop(self) -> None:
        """Stop the processor, draining remaining events."""
        if not self._running:
            return

        logger.info("Stopping Document Access Processor...")
        self._running = False

        # finish remaining events
        drained_count = 0
        while not self._queue.empty():
            try:
                event = self._queue.get_nowait()
                await self._process_event(event)
                self._queue.task_done()
                drained_count += 1
            except asyncio.QueueEmpty:
                break
            except Exception as e:
                logger.exception(f"Error draining event: {e}")

        if drained_count > 0:
            logger.info(f"Drained {drained_count} events during shutdown")

        # Cancel background task in the main event loop
        if self._task:
            self._task.cancel()
            with contextlib.suppress(
                asyncio.CancelledError
            ):  # we expect the cancelation
                await self._task

        logger.info("Document Access Processor stopped")

    async def enqueue(self, event: DocumentAccessEvent) -> None:
        """Add an event to the processing queue.

        Args:
            event: The document access event to process
        """
        await self._queue.put(event)
        logger.debug(f"Enqueued event {event.event_id} for URL {event.url}")

    async def _process_loop(self) -> None:
        """Main processing loop - runs until stopped."""
        while self._running:
            try:
                # Wait for event with timeout to allow 'running' state updates
                event = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0,
                )
                await self._process_event(event)
                self._queue.task_done()
            except TimeoutError:
                # No event received - check _running flag
                continue
            except asyncio.CancelledError:
                # Task cancelled during shutdown
                break
            except Exception as e:
                logger.exception(f"Error in process loop: {e}")

    async def _process_event(self, event: DocumentAccessEvent) -> None:
        """Process a single document access event.

        Deduplication: Handled inside process_event_atomically via transaction.
        Atomicity: All counter updates happen in a single transaction.

        Args:
            event: The document access event to process
        """
        # dedup check + mark + counter updates executed atomically - all or nothing (worker crashes / restarts correctness)
        processed = await process_event_atomically(
            event_id=event.event_id,
            url=event.url,
            url_hash=event.url_hash,
            domain=event.domain,
            timestamp=event.timestamp,
        )

        if not processed:
            logger.debug(f"Event {event.event_id} already processed")
            return

        logger.info(f"Processed event {event.event_id} for URL: {event.url}")

        # Handle enrichment outside transaction since it is not part of the atomic counters update
        await self._handle_enrichment(event.url)

    async def _handle_enrichment(self, url: str) -> None:
        """Handle URL enrichment with retry logic
        * uses exponential backoff: 1s, 2s, 4s, 8s, 16s (max 5 retries)
        """
        # check if already enriched - improves latency and unstable resource stability (partial failures during enrichment correctness)
        if await is_enriched(url):
            logger.debug(f"URL already enriched: {url}")
            return

        # enrich url with exponential backoff (retries correctness)
        result = await self._enrichment_client.enrich(url)

        if result.enriched:
            await mark_enriched(url)
            logger.info(f"Successfully enriched URL: {url}")
        else:
            # Enrichment failed after all retries
            # Log but don't fail - enrichment is best-effort
            logger.warning(f"Failed to enrich URL after retries: {url}")


# Global processor instance
processor = DocumentAccessProcessor()
