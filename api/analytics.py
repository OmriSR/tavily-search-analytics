"""Analytics API endpoints."""

import logging

from fastapi import APIRouter, HTTPException

from core.models.schemas import DomainAnalytics, QueryAnalytics, UrlAnalytics
from data.analytics_repo import get_domain_stats, get_query_stats, get_url_stats

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/query/{query_hash}", response_model=QueryAnalytics)
async def get_query_analytics(query_hash: str) -> QueryAnalytics:
    """Get analytics for a specific query by its hash"""
    stats = await get_query_stats(query_hash)

    if stats is None:
        raise HTTPException(
            status_code=404,
            detail=f"No analytics found for query hash: {query_hash}",
        )

    return QueryAnalytics(**stats)


@router.get("/url/{url_hash}", response_model=UrlAnalytics)
async def get_url_analytics(url_hash: str) -> UrlAnalytics:
    """Get analytics for a specific URL by its hash"""
    stats = await get_url_stats(url_hash)

    if stats is None:
        raise HTTPException(
            status_code=404,
            detail=f"No analytics found for URL hash: {url_hash}",
        )

    return UrlAnalytics(**stats)


@router.get("/domain/{domain}", response_model=DomainAnalytics)
async def get_domain_analytics(domain: str) -> DomainAnalytics:
    """Get aggregated analytics for a specific domain"""
    stats = await get_domain_stats(domain)

    if stats is None:
        raise HTTPException(
            status_code=404,
            detail=f"No analytics found for domain: {domain}",
        )

    return DomainAnalytics(**stats)
