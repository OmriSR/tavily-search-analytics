# Tavily Search Analytics Service

## Setup Instructions

### Prerequisites
- Python 3.11+

### Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file in the project root (see .env.example):
```
TAVILY_API_KEY=your_tavily_api_key
OPENAI_API_KEY=your_openai_api_key
```

## Running the Service

Start both services:

**Terminal 1 - Enricher Service (port 8001):**
```bash
uvicorn enricher_service:app --port 8001
```

**Terminal 2 - Main Service (port 8000):**
```bash
uvicorn main:app --port 8000
```

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
