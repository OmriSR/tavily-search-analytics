"""Analytics API endpoints."""

import logging
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException

from models.schemas import DomainAnalytics, QueryAnalytics, UrlAnalytics
from storage.analytics_repo import get_domain_stats, get_query_stats, get_url_stats

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/query/{query_hash}", response_model=QueryAnalytics)
async def get_query_analytics(query_hash: str) -> QueryAnalytics:
    """Get analytics for a specific query by its hash.

    Returns query stats including avg_response_time_ms.
    """
    stats = await get_query_stats(query_hash)

    if stats is None:
        raise HTTPException(
            status_code=404,
            detail=f"No analytics found for query hash: {query_hash}",
        )

    return QueryAnalytics(**stats)


@router.get("/url/{url_path:path}", response_model=UrlAnalytics)
async def get_url_analytics(url_path: str) -> UrlAnalytics:
    """Get analytics for a specific URL.

    The URL is passed as a path parameter and may be URL-encoded.
    """
    url = unquote(url_path)

    stats = await get_url_stats(url)

    if stats is None:
        raise HTTPException(
            status_code=404,
            detail=f"No analytics found for URL: {url}",
        )

    return UrlAnalytics(**stats)


@router.get("/domain/{domain}", response_model=DomainAnalytics)
async def get_domain_analytics(domain: str) -> DomainAnalytics:
    """Get aggregated analytics for a specific domain."""
    stats = await get_domain_stats(domain)

    if stats is None:
        raise HTTPException(
            status_code=404,
            detail=f"No analytics found for domain: {domain}",
        )

    return DomainAnalytics(**stats)
