"""Tavily API client for search operations."""

import logging
from dataclasses import dataclass

import httpx

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class TavilyResult:
    """Single search result from Tavily API."""

    title: str
    url: str
    content: str
    score: float


@dataclass
class TavilySearchResult:
    """Complete Tavily API search response."""

    query: str
    answer: str
    results: list[TavilyResult]
    response_time_ms: float  # Converted from string seconds to float milliseconds
    request_id: str


class TavilyClient:
    """Async client for Tavily Search API."""

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize Tavily client with API key."""
        self._api_key = api_key or settings.tavily_api_key
        self._api_url = settings.tavily_api_url
        if not self._api_key:
            raise ValueError("Tavily API key is required")

    def _convert_response_time(self, response_time_str: str) -> float:
        """Convert response_time from string seconds to float milliseconds.

        Tavily returns: "1.67" (string, seconds)
        We need: 1670.0 (float, milliseconds)

        Args:
            response_time_str: Response time as string in seconds (e.g., "1.67")

        Returns:
            Response time as float in milliseconds (e.g., 1670.0)
        """
        return float(response_time_str) * 1000.0

    async def search(self, query: str) -> TavilySearchResult:
        """Execute a search query against Tavily API.

        Args:
            query: The search query string

        Returns:
            TavilySearchResult with query, answer, results, response_time_ms, and request_id

        Raises:
            httpx.HTTPStatusError: If the API returns an error status
            httpx.RequestError: If there's a network error
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._api_url,
                json={"query": query, "api_key": self._api_key},
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

            # Convert response_time string to milliseconds
            response_time_ms = self._convert_response_time(data["response_time"])

            # Parse results
            results = [
                TavilyResult(
                    title=r.get("title", ""),
                    url=r["url"],
                    content=r.get("content", ""),
                    score=r.get("score", 0.0),
                )
                for r in data.get("results", [])
            ]

            logger.info(
                f"Tavily search completed: query='{query[:50]}...', "
                f"results={len(results)}, response_time={response_time_ms}ms"
            )

            return TavilySearchResult(
                query=data["query"],
                answer=data.get("answer", ""),
                results=results,
                response_time_ms=response_time_ms,
                request_id=data["request_id"],
            )
