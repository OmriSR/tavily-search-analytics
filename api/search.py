"""Search API endpoint."""

import hashlib
import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, HTTPException

from config import settings
from core.document_access_processor import processor
from core.models.events import DocumentAccessEvent
from core.models.schemas import SearchRequest, SearchResponse, Source
from core.services.llm_service import LLMService
from core.services.tavily_client import TavilyClient, TavilySearchResult
from data.analytics_repo import update_query_stats

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


async def _generate_llm_answer(
    query: str,
    tavily_result: TavilySearchResult,
) -> str:
    """Generate answer using LLM with Tavily context, fallback to Tavily answer."""
    contexts = [
        {"url": r.url, "title": r.title, "content": r.content}
        for r in tavily_result.results
    ]
    try:
        return await llm_service.generate_answer(
            query=query,
            tavily_answer=tavily_result.answer,
            contexts=contexts,
        )
    except Exception as e:
        logger.error(f"LLM error: {e}")
        return tavily_result.answer


async def _process_search_analytics(
    query_hash: str,
    query_text: str,
    tavily_result: TavilySearchResult,
) -> None:
    """Emit document access events and update query stats (runs in background)."""
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

    await update_query_stats(
        query_hash=query_hash,
        query_text=query_text,
        response_time_ms=tavily_result.response_time_ms,
        success=True,
        urls=urls,
    )


@router.post("/search", response_model=SearchResponse)
async def search(
    request: SearchRequest, background_tasks: BackgroundTasks
) -> SearchResponse:
    """Execute a search query and return AI-generated answer with sources.

    Flow:
    1. Call Tavily API for search results
    2. Generate enhanced answer via LLM
    3. Return response immediately
    4. Schedule analytics processing in background
    """
    query_hash = compute_query_hash(request.query)

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

    answer = await _generate_llm_answer(request.query, tavily_result)

    sources = [
        Source(
            url=r.url, title=r.title, snippet=r.content[: settings.snippet_max_length]
        )
        for r in tavily_result.results
    ]
    response = SearchResponse(
        request_id=tavily_result.request_id,
        query=request.query,
        query_hash=query_hash,
        answer=answer,
        sources=sources,
        created_at=datetime.now(UTC).isoformat(),
    )

    # Schedule analytics processing after response is sent for reduced latancy
    background_tasks.add_task(
        _process_search_analytics, query_hash, request.query, tavily_result
    )

    return response
