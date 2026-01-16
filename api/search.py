"""Search API endpoint."""

import hashlib
import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException

from config import settings
from models.events import DocumentAccessEvent
from models.schemas import SearchRequest, SearchResponse, Source
from processors.document_access import processor
from services.llm_service import LLMService
from services.tavily_client import TavilyClient
from storage.analytics_repo import update_query_stats
from storage.cache import cache_response, get_cached_response

logger = logging.getLogger(__name__)
router = APIRouter()

# Service instances
tavily_client = TavilyClient()
llm_service = LLMService()


def compute_query_hash(query: str) -> str:
    """Compute SHA-256 hash of query for caching/tracking."""
    return hashlib.sha256(query.encode()).hexdigest()


def extract_domain(url: str) -> str:
    """Extract full domain (including subdomain) from URL."""
    parsed = urlparse(url)
    return parsed.netloc


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    """Execute a search query and return AI-generated answer with sources.

    Flow:
    1. Check cache for existing response
    2. Call Tavily API for search results
    3. Generate enhanced answer via LLM
    4. Emit document access events for analytics
    5. Update query stats (synchronous for simplicity)
    6. Cache and return response
    """
    query_hash = compute_query_hash(request.query)

    # check cache and fast return if hit
    cached = await get_cached_response(query_hash)
    if cached:
        logger.info(f"Cache hit for query: {request.query[:50]}...")
        cached["is_cached_response"] = True
        return SearchResponse(**cached)

    # get data using Tavily API
    try:
        tavily_result = await tavily_client.search(request.query)
    except Exception as e:
        logger.error(f"Tavily API error: {e}")
        await update_query_stats(
            query_hash=query_hash,
            query_text=request.query,
            response_time_ms=0.0,
            success=False,
            urls=[],
        )
        raise HTTPException(status_code=503, detail="Search service unavailable") from e

    contexts_for_llm = [
        {"url": r.url, "title": r.title, "content": r.content}
        for r in tavily_result.results
    ]

    # call llm with query and context (fall back to Tavily's given answer)
    try:
        answer = await llm_service.generate_answer(
            query=request.query,
            tavily_answer=tavily_result.answer,
            contexts=contexts_for_llm,
        )
    except Exception as e:
        logger.error(f"LLM error: {e}")
        answer = tavily_result.answer

    # add event to queue to process url and domain anlytics in background
    urls = []
    for result in tavily_result.results:
        domain = extract_domain(result.url)
        urls.append(result.url)

        event = DocumentAccessEvent(
            url=result.url,
            domain=domain,
            query_hash=query_hash,
            request_id=tavily_result.request_id,
        )
        await processor.enqueue(event)

    # Step 5: Update query stats (synchronous for simplicity)
    await update_query_stats(
        query_hash=query_hash,
        query_text=request.query,
        response_time_ms=tavily_result.response_time_ms,
        success=True,
        urls=urls,
    )

    # Step 6: Build response
    created_at = datetime.now(UTC).isoformat()
    sources = [
        Source(url=r.url, title=r.title, snippet=r.content[:200])
        for r in tavily_result.results
    ]

    response = SearchResponse(
        request_id=tavily_result.request_id,
        query=request.query,
        query_hash=query_hash,
        answer=answer,
        sources=sources,
        created_at=created_at,
        is_cached_response=False,
    )

    # Step 7: Cache response
    await cache_response(
        query_hash=query_hash,
        response=response.model_dump(),
        ttl_seconds=settings.cache_ttl_seconds,
    )

    return response
