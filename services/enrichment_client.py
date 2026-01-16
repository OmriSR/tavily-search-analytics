"""HTTP client for enricher service with exponential backoff retry."""

import asyncio
import logging

import httpx

from config import settings
from models.schemas import EnrichResponse

logger = logging.getLogger(__name__)


class EnrichmentClient:
    """HTTP client for enricher service with exponential backoff retry.

    Implements retry logic with exponential backoff:
    - Retry delays: 1s, 2s, 4s, 8s, 16s
    - Max 5 retries (configurable)
    """

    def __init__(
        self,
        base_url: str | None = None,
        max_retries: int | None = None,
        base_delay: float | None = None,
    ) -> None:
        """Initialize enrichment client.

        Args:
            base_url: Base URL of the enricher service
            max_retries: Maximum number of retry attempts
            base_delay: Base delay in seconds for exponential backoff
        """
        self._base_url = base_url or settings.enricher_service_url
        self._max_retries = max_retries or settings.max_retries
        self._base_delay = base_delay or settings.retry_base_delay_seconds

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay.

        Args:
            attempt: Current attempt number (0-indexed)

        Returns:
            Delay in seconds for the given attempt

        Examples:
            attempt 0 -> 1s
            attempt 1 -> 2s
            attempt 2 -> 4s
            attempt 3 -> 8s
            attempt 4 -> 16s
        """
        return self._base_delay * (2**attempt)

    async def enrich(self, url: str) -> EnrichResponse:
        """Attempt to enrich a URL with exponential backoff retry.

        Returns EnrichResponse with enriched=True on success, enriched=False on failure.
        """
        last_exception: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self._base_url}/enrich",
                        json={"url": url},
                        timeout=2.0,
                    )
                    response.raise_for_status()  # raise error for failed enrichment
                    data: dict = response.json()
                    return EnrichResponse(url=url, enriched=data.get("enriched", False))

            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                last_exception = e

                if attempt < self._max_retries - 1:
                    delay = self._calculate_delay(attempt)
                    logger.warning(
                        f"Enrichment failed for {url}, attempt {attempt + 1}/{self._max_retries}. "
                        f"Retrying in {delay}s. Error: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Enrichment failed for {url} after {self._max_retries} attempts. "
                        f"Final error: {last_exception}"
                    )

        return EnrichResponse(url=url, enriched=False)
