# Tavily Search Analytics Service

## Setup Instructions

### Prerequisites
- Python 3.11+

### Installation

1. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set environment variables:
```bash
export TAVILY_API_KEY=your_tavily_api_key
export OPENAI_API_KEY=your_openai_api_key
```

Or create a `.env` file in the project root:
```
TAVILY_API_KEY=your_tavily_api_key
OPENAI_API_KEY=your_openai_api_key
```

## Running the Service

Start both services in separate terminals:

**Terminal 1 - Enricher Service (port 8001):**
```bash
uvicorn enricher_service:app --port 8001
```

**Terminal 2 - Main Service (port 8000):**
```bash
uvicorn main:app --port 8000
```

### Verify it works

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "What is Python?"}'
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Main Service (port 8000)                  │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │  POST /search │◀──▶│  Tavily API  │    │  asyncio.Queue   │  │
│  │  (user query) │    │  + LangChain │───▶│  (events)        │  │
│  └───────┬──────┘    └──────────────┘    └────────┬─────────┘  │
│          │                                        │            │
│          │ writes query stats                     ▼            │
│          │             ┌──────────────────────────────────────┐│
│          │             │     Document Access Processor        ││
│  ┌───────▼──────┐      │  - Deduplication (event_id)          ││
│  │ GET /analytics│◀────│  - URL/Domain counters               ││
│  └──────────────┘      │  - Enrichment with retries           ││
│                        └──────────────────────────┬───────────┘│
│  ┌────────────────────────────────────────────────────────────┐│
│  │                    SQLite Storage                          ││
│  │  - query_stats, query_cache                                ││
│  │  - url_stats, domain_stats                                 ││
│  │  - processed_events (deduplication)                        ││
│  └────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                                │ HTTP (exponential backoff)
┌─────────────────────────────────────────────────────────────────┐
│              Enricher Service (port 8001)                        │
│              POST /enrich - 30% failure rate                     │
└─────────────────────────────────────────────────────────────────┘
```

**Data Flow:**
1. `POST /search` receives query, calls Tavily API and LLM
2. Search endpoint writes query statistics directly to `query_stats` table
3. Document access events are queued for background processing
4. Document Access Processor deduplicates events and updates `url_stats`/`domain_stats`
5. Processor calls Enricher Service with exponential backoff retries

---

## API Documentation

### POST /search

Submit a query and receive an AI-generated answer with sources.

**Request:**
```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "What is quantum computing?"}'
```

**Response:**
```json
{
  "request_id": "abc123",
  "query": "What is quantum computing?",
  "query_hash": "sha256hash...",
  "answer": "Quantum computing is a type of computation...",
  "sources": [
    {
      "url": "https://example.com/quantum",
      "title": "Introduction to Quantum Computing",
      "snippet": "Quantum computing uses quantum mechanics..."
    }
  ],
  "created_at": "2024-01-15T10:30:00+00:00",
  "is_cached_response": false
}
```

### GET /analytics/query/{query_hash}

Get statistics for a specific query by its hash.

**Request:**
```bash
curl http://localhost:8000/analytics/query/{query_hash}
```

**Response:**
```json
{
  "query_hash": "sha256hash...",
  "query": "What is quantum computing?",
  "total_requests": 10,
  "successful_requests": 9,
  "failed_requests": 1,
  "first_seen": "2024-01-10T08:00:00+00:00",
  "last_seen": "2024-01-15T10:30:00+00:00",
  "avg_response_time_ms": 1250.5,
  "urls": ["https://example.com/quantum", "https://docs.example.com/intro"]
}
```

### GET /analytics/url/{url}

Get access statistics for a specific URL.

**Request:**
```bash
curl http://localhost:8000/analytics/url/https%3A%2F%2Fexample.com%2Fquantum
```

**Response:**
```json
{
  "url": "https://example.com/quantum",
  "domain": "example.com",
  "access_count": 15,
  "first_accessed": "2024-01-10T08:00:00+00:00",
  "last_accessed": "2024-01-15T10:30:00+00:00",
  "enriched": true
}
```

### GET /analytics/domain/{domain}

Get aggregated statistics for a specific domain.

**Request:**
```bash
curl http://localhost:8000/analytics/domain/example.com
```

**Response:**
```json
{
  "domain": "example.com",
  "access_count": 150,
  "unique_urls": 25,
  "first_accessed": "2024-01-01T00:00:00+00:00",
  "last_accessed": "2024-01-15T10:30:00+00:00",
  "urls": [
    "https://example.com/page1",
    "https://example.com/page2"
  ]
}
```

### GET /health

Health check endpoint for service monitoring.

**Request:**
```bash
curl http://localhost:8000/health
```

**Response:**
```json
{
  "status": "healthy"
}
```

---

## Design Decisions & Tradeoffs

### Domain Definition: Full Subdomain vs Root Domain

**Choice:** Full subdomain (e.g., `docs.example.com`)

| Aspect | Full Subdomain | Root Domain |
|--------|----------------|-------------|
| **Performance** | More unique keys in DB | Fewer keys, faster lookups |
| **Accuracy** | Distinguishes `api.github.com` from `docs.github.com` | Treats all subdomains as same source |
| **Complexity** | Simple URL parsing | Needs public suffix list for edge cases |
| **Recommendation** | Better for analytics accuracy | Better for aggregated reporting |

We chose full subdomain because analytics accuracy is more valuable for understanding which specific services/docs are being accessed.

### GIL and Batching

**Choice:** Async processing without batching

| Aspect | Async Processing | Batching |
|--------|------------------|----------|
| **GIL Impact** | Releases during await (I/O) | N/A |
| **Latency** | Events processed immediately | Adds batch delay |
| **Complexity** | Simple event loop | Batch management logic |
| **Throughput** | Good for I/O-bound work | Better for CPU-bound work |

Since the Document Access Processor is I/O-bound (HTTP calls to enricher, SQLite writes), the GIL releases during `await` operations. Batching would add latency without significant benefit. For CPU-bound work, batching with multiprocessing would be preferred.

### Idempotency

**Choice:** UUID-based event deduplication via `processed_events` table

Each `DocumentAccessEvent` gets a unique UUID (`event_id`). Before processing, we check if the event_id exists in the `processed_events` table. This ensures:
- Duplicate events (from retries, network issues) are processed exactly once
- Counters remain accurate even under at-least-once delivery semantics

### Retry Strategy

**Choice:** Exponential backoff with max 5 retries (1s, 2s, 4s, 8s, 16s)

The enricher service has a 30% simulated failure rate. Our retry strategy:
- Starts with 1 second delay
- Doubles delay on each failure (exponential backoff)
- Maximum 5 retries (31 seconds total wait)
- Prevents thundering herd problem
- Allows transient failures to recover

---

## Testing

### Run All Tests

```bash
pytest tests/ -v
```

### Run Specific Test File

```bash
pytest tests/test_integration.py -v
```

### Run with Coverage

```bash
pytest --cov=. tests/
```

### Key Correctness Tests

The integration tests verify:
- Duplicate events are idempotent (counters don't double-count)
- Retry logic uses exponential backoff
- Counters remain correct after partial failures
- Concurrent events maintain atomicity
- Service restart doesn't lose processed events

---

## What I Would Add With More Time

1. **Redis for queue persistence** - Survive complete service restarts without losing events
2. **Distributed locking** - Support multiple processor workers for horizontal scaling
3. **Prometheus metrics** - Track processing latency, enrichment failure rate, queue depth
4. **Rate limiting** - Protect against abuse and control API costs
5. **Dead letter queue** - Track permanently failed enrichments for manual review
6. **Database migrations** - Alembic for schema evolution
7. **Structured logging** - JSON logs with correlation IDs for debugging
8. **Circuit breaker pattern** - Stop calling enricher after N consecutive failures
9. **Health check endpoints** - `/ready` endpoint for orchestration readiness checks
10. **Load testing** - Locust or k6 to verify behavior under load