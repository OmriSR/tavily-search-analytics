"""Pydantic models for API requests and responses."""

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Request model for search endpoint."""

    query: str = Field(..., min_length=1, description="The search query")


class Source(BaseModel):
    """A source document returned from search."""

    url: str
    title: str
    snippet: str


class SearchResponse(BaseModel):
    """Response model for search endpoint."""

    request_id: str
    query: str
    query_hash: str
    answer: str
    sources: list[Source]
    created_at: str


class QueryAnalytics(BaseModel):
    """Analytics for a specific query."""

    query_hash: str
    query: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    first_seen: str
    last_seen: str
    avg_response_time_ms: float
    urls: list[str]


class UrlAnalytics(BaseModel):
    """Analytics for a specific URL."""

    url_hash: str
    url: str
    domain: str
    access_count: int
    first_accessed: str
    last_accessed: str
    enriched: bool = False


class DomainAnalytics(BaseModel):
    """Analytics for a specific domain."""

    domain: str
    access_count: int
    unique_urls: int
    first_accessed: str
    last_accessed: str
    urls: list[str]


class EnrichRequest(BaseModel):
    """Request model for enrichment endpoint."""

    url: str


class EnrichResponse(BaseModel):
    """Response model for enrichment endpoint."""

    url: str
    enriched: bool
    message: str = ""
