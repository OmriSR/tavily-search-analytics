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
