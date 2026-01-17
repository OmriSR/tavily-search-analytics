"""Standalone enricher service for URL enrichment simulation."""

import asyncio
import logging
import random

from fastapi import FastAPI, HTTPException

from config import settings
from core.models.schemas import EnrichRequest, EnrichResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Enricher Service",
    description="Simulates URL enrichment with configurable failure rate",
    version="1.0.0",
)


@app.post("/enrich", response_model=EnrichResponse)
async def enrich_url(request: EnrichRequest) -> EnrichResponse:
    """
    Enrich a URL with additional metadata
    * Simulates processing with random failures (about ~30% of requests will fail)
    * the failing rate can be set in settings
    """
    logger.info(f"Enrichment request for URL: {request.url}")

    # processing delay
    await asyncio.sleep(settings.enricher_delay_seconds)

    # random failures (if a random number over uniform distribution is smaller than the failure rate - fail)
    if random.random() < settings.enricher_failure_rate:
        logger.warning(f"Simulated failure for URL: {request.url}")
        raise HTTPException(
            status_code=500,
            detail="Simulated enrichment failure",
        )

    logger.info(f"Successfully enriched URL: {request.url}")
    return EnrichResponse(
        url=request.url,
        enriched=True,
        message="URL successfully enriched",
    )


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "enricher"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.enricher_service_port)
