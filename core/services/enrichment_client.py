import asyncio
import logging
import httpx
from config import settings
from core.models.schemas import EnrichResponse

logger = logging.getLogger(__name__)


class EnrichmentClient:
    """
    HTTP client for enricher service with exponential backoff retry"
    * max_retires and the base_delay can be configured in settings or on init
    """

    def __init__(
        self,
        base_url: str | None = None,
        max_retries: int | None = None,
        base_delay: float | None = None,
    ) -> None:
        """
        can be manualy set or use default:
            base_url: Base URL of the enricher service
            max_retries: Maximum number of retry attempts
            base_delay: Base delay in seconds for exponential backoff
        """
        self._base_url = base_url or settings.enricher_service_url
        self._max_retries = max_retries or settings.max_retries
        self._base_delay = base_delay or settings.retry_base_delay_seconds

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay"""
        return self._base_delay * (2**attempt)

    async def enrich(self, url: str) -> EnrichResponse:
        """
        Attempt to enrich a URL with exponential backoff retry
        returns EnrichResponse with enriched=True on success, enriched=False on failure.
        """
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
