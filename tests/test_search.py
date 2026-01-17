"""Tests for search endpoint and related functionality."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks

from api.search import compute_query_hash, compute_url_hash, extract_domain
from core.models.schemas import SearchRequest, SearchResponse
from core.services.tavily_client import TavilyResult, TavilySearchResult


class TestQueryHash:
    """Tests for query hash computation."""

    def test_compute_query_hash_deterministic(self) -> None:
        """Same query should produce same hash."""
        query = "What is quantum computing?"
        hash1 = compute_query_hash(query)
        hash2 = compute_query_hash(query)
        assert hash1 == hash2

    def test_compute_query_hash_different_queries(self) -> None:
        """Different queries should produce different hashes."""
        hash1 = compute_query_hash("What is quantum computing?")
        hash2 = compute_query_hash("What is machine learning?")
        assert hash1 != hash2

    def test_compute_query_hash_is_sha256(self) -> None:
        """Hash should be 64 character hex string (SHA-256)."""
        query_hash = compute_query_hash("test query")
        assert len(query_hash) == 64
        assert all(c in "0123456789abcdef" for c in query_hash)


class TestUrlHash:
    """Tests for URL hash computation."""

    def test_compute_url_hash_deterministic(self) -> None:
        """Same URL should produce same hash."""
        url = "https://example.com/page"
        hash1 = compute_url_hash(url)
        hash2 = compute_url_hash(url)
        assert hash1 == hash2

    def test_compute_url_hash_different_urls(self) -> None:
        """Different URLs should produce different hashes."""
        hash1 = compute_url_hash("https://example.com/page1")
        hash2 = compute_url_hash("https://example.com/page2")
        assert hash1 != hash2

    def test_compute_url_hash_is_sha256(self) -> None:
        """Hash should be 64 character hex string (SHA-256)."""
        url_hash = compute_url_hash("https://example.com/test")
        assert len(url_hash) == 64
        assert all(c in "0123456789abcdef" for c in url_hash)


class TestDomainExtraction:
    """Tests for domain extraction from URLs."""

    def test_extract_domain_basic(self) -> None:
        """Extract domain from basic URL."""
        assert extract_domain("https://example.com/page") == "example.com"

    def test_extract_domain_with_subdomain(self) -> None:
        """Extract full subdomain, not just root domain."""
        assert extract_domain("https://docs.example.com/page") == "docs.example.com"
        assert (
            extract_domain("https://api.v2.example.com/endpoint")
            == "api.v2.example.com"
        )

    def test_extract_domain_with_port(self) -> None:
        """Domain should include port if present."""
        assert extract_domain("http://localhost:8000/api") == "localhost:8000"

    def test_extract_domain_http(self) -> None:
        """Works with http scheme."""
        assert extract_domain("http://example.com/page") == "example.com"


@pytest.mark.asyncio
async def test_search_returns_valid_response_format(initialized_test_db) -> None:
    """Verify search endpoint returns correctly formatted response."""
    mock_tavily_result = TavilySearchResult(
        query="test query",
        answer="This is the Tavily answer",
        results=[
            TavilyResult(
                title="Test Result 1",
                url="https://example.com/result1",
                content="Content of result 1 with enough text to create a snippet.",
                score=0.95,
            ),
            TavilyResult(
                title="Test Result 2",
                url="https://docs.example.com/result2",
                content="Content of result 2 with more information.",
                score=0.90,
            ),
        ],
        response_time_ms=150.0,
        request_id="test-request-123",
    )

    mock_llm_answer = "This is the enhanced LLM answer."

    with (
        patch("api.search.tavily_client.search", new_callable=AsyncMock) as mock_tavily,
        patch(
            "api.search.llm_service.generate_answer", new_callable=AsyncMock
        ) as mock_llm,
        patch("api.search.processor.enqueue", new_callable=AsyncMock),
    ):
        mock_tavily.return_value = mock_tavily_result
        mock_llm.return_value = mock_llm_answer

        from api.search import search

        request = SearchRequest(query="test query")
        mock_background_tasks = MagicMock(spec=BackgroundTasks)
        response = await search(request, mock_background_tasks)

        # Verify response format
        assert isinstance(response, SearchResponse)
        assert response.request_id == "test-request-123"
        assert response.query == "test query"
        assert response.answer == mock_llm_answer
        assert len(response.sources) == 2

        # Verify sources
        assert response.sources[0].url == "https://example.com/result1"
        assert response.sources[0].title == "Test Result 1"
        assert response.sources[1].url == "https://docs.example.com/result2"

        # Verify background task was scheduled
        mock_background_tasks.add_task.assert_called_once()


@pytest.mark.asyncio
async def test_search_extracts_sources_correctly(initialized_test_db) -> None:
    """Verify sources list is populated from Tavily results."""
    mock_tavily_result = TavilySearchResult(
        query="test query",
        answer="Answer",
        results=[
            TavilyResult(
                title="Wikipedia Article",
                url="https://en.wikipedia.org/wiki/Test",
                content="Wikipedia content about the test topic with detailed information.",
                score=0.98,
            ),
            TavilyResult(
                title="Documentation",
                url="https://docs.python.org/3/library/test.html",
                content="Official documentation content.",
                score=0.95,
            ),
            TavilyResult(
                title="Stack Overflow",
                url="https://stackoverflow.com/questions/12345",
                content="Community discussion about the topic.",
                score=0.92,
            ),
        ],
        response_time_ms=200.0,
        request_id="sources-test-123",
    )

    with (
        patch("api.search.tavily_client.search", new_callable=AsyncMock) as mock_tavily,
        patch(
            "api.search.llm_service.generate_answer", new_callable=AsyncMock
        ) as mock_llm,
        patch("api.search.processor.enqueue", new_callable=AsyncMock),
    ):
        mock_tavily.return_value = mock_tavily_result
        mock_llm.return_value = "LLM answer"

        from api.search import search

        request = SearchRequest(query="test query")
        mock_background_tasks = MagicMock(spec=BackgroundTasks)
        response = await search(request, mock_background_tasks)

        # Verify all 3 sources extracted
        assert len(response.sources) == 3

        # Check specific sources
        urls = [s.url for s in response.sources]
        assert "https://en.wikipedia.org/wiki/Test" in urls
        assert "https://docs.python.org/3/library/test.html" in urls
        assert "https://stackoverflow.com/questions/12345" in urls

        # Verify titles
        titles = [s.title for s in response.sources]
        assert "Wikipedia Article" in titles
        assert "Documentation" in titles
        assert "Stack Overflow" in titles


@pytest.mark.asyncio
async def test_search_emits_document_access_events(initialized_test_db) -> None:
    """Verify document access events are enqueued for each search result."""
    mock_tavily_result = TavilySearchResult(
        query="event emission test",
        answer="Answer",
        results=[
            TavilyResult(
                title="Result 1",
                url="https://source1.example.com/page",
                content="Content 1",
                score=0.9,
            ),
            TavilyResult(
                title="Result 2",
                url="https://source2.example.com/page",
                content="Content 2",
                score=0.85,
            ),
        ],
        response_time_ms=100.0,
        request_id="event-test-123",
    )

    with (
        patch("api.search.tavily_client.search", new_callable=AsyncMock) as mock_tavily,
        patch(
            "api.search.llm_service.generate_answer", new_callable=AsyncMock
        ) as mock_llm,
        patch("api.search.processor.enqueue", new_callable=AsyncMock) as mock_enqueue,
    ):
        mock_tavily.return_value = mock_tavily_result
        mock_llm.return_value = "LLM answer"

        from api.search import _process_search_analytics, search

        request = SearchRequest(query="event emission test")
        mock_background_tasks = MagicMock(spec=BackgroundTasks)
        await search(request, mock_background_tasks)

        # Verify background task was scheduled with analytics processing
        mock_background_tasks.add_task.assert_called_once()
        call_args = mock_background_tasks.add_task.call_args
        assert call_args[0][0] == _process_search_analytics

        # Execute the background task to verify events are enqueued
        await _process_search_analytics(
            call_args[0][1],  # query_hash
            call_args[0][2],  # query_text
            call_args[0][3],  # tavily_result
        )

        # Verify enqueue was called for each result
        assert mock_enqueue.call_count == 2

        # Verify event URLs match results
        enqueued_urls = [call.args[0].url for call in mock_enqueue.call_args_list]
        assert "https://source1.example.com/page" in enqueued_urls
        assert "https://source2.example.com/page" in enqueued_urls


@pytest.mark.asyncio
async def test_search_llm_failure_falls_back_to_tavily_answer(
    initialized_test_db,
) -> None:
    """If LLM fails, should fall back to Tavily's answer."""
    mock_tavily_result = TavilySearchResult(
        query="fallback test",
        answer="Tavily fallback answer",
        results=[
            TavilyResult(
                title="Result",
                url="https://example.com",
                content="Content",
                score=0.9,
            ),
        ],
        response_time_ms=100.0,
        request_id="fallback-test-123",
    )

    with (
        patch("api.search.tavily_client.search", new_callable=AsyncMock) as mock_tavily,
        patch(
            "api.search.llm_service.generate_answer", new_callable=AsyncMock
        ) as mock_llm,
        patch("api.search.processor.enqueue", new_callable=AsyncMock),
    ):
        mock_tavily.return_value = mock_tavily_result
        mock_llm.side_effect = Exception("LLM service error")

        from api.search import search

        request = SearchRequest(query="fallback test")
        mock_background_tasks = MagicMock(spec=BackgroundTasks)
        response = await search(request, mock_background_tasks)

        # Should use Tavily's answer as fallback
        assert response.answer == "Tavily fallback answer"


@pytest.mark.asyncio
async def test_search_request_validation() -> None:
    """Verify SearchRequest validates query is not empty."""
    with pytest.raises(ValueError):
        SearchRequest(query="")
