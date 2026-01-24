# Tavily Search Analytics Service

A backend service for a "search + answer" product that combines Tavily search with LLM-generated answers and tracks document access analytics

![Tavily Search Analytics Architecture](https://github.com/user-attachments/assets/31086731-e133-4864-8f75-e567d09b5406)

## Setup Instructions

### Prerequisites
- Python 3.11+

### Installation

1. Clone the repository and navigate to the project directory.

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project root with your API keys (see .env.example):
```
TAVILY_API_KEY=your_tavily_api_key
OPENAI_API_KEY=your_openai_api_key
```

## Running the Service Locally
The service consists of two components that need to run simultaneously.

**Terminal 1 - Start the Enricher Service:**
```bash
uvicorn enricher_service:app --port 8001
```

**Terminal 2 - Start the Main Service:**
```bash
uvicorn main:app --port 8000
```

Once both services are running, the API is available at `http://localhost:8000`.

### Quick Start

Make a search request:
```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "How to review an home assignment?"}'
```

Retrieve statistics for a specific query:
```bash
curl http://localhost:8000/analytics/query/abc123def456
```

Retrieve access statistics for a specific URL:
```bash
curl http://localhost:8000/analytics/url/xyz789hash
```

Retrieve aggregated statistics for a domain:
```bash
curl http://localhost:8000/analytics/domain/docs.example.com
```

