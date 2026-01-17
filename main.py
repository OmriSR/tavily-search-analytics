import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config import settings
from data.database import get_database_connection, init_database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan - startup and shutdown events."""
    logger.info("Starting Tavily Search Analytics Service...")

    await init_database()
    logger.info(f"Database initialized at {settings.database_path}")

    from core.document_access_processor import processor

    await processor.start()
    logger.info("Document Access Processor started")

    yield

    # Shutdown
    logger.info("Shutting down...")
    await processor.stop()
    logger.info("Document Access Processor stopped")


app = FastAPI(
    title="Tavily Search Analytics Service",
    description="Backend service for search + answer with document access analytics",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint with database verification."""
    try:
        async with get_database_connection() as db:
            await db.execute("SELECT 1")
        return {"status": "healthy"}
    except Exception:
        return {"status": "unhealthy"}


# Import and include routers after app is created
def setup_routers() -> None:
    """Set up API routers."""
    from api.analytics import router as analytics_router
    from api.search import router as search_router

    app.include_router(search_router, tags=["search"])
    app.include_router(analytics_router, prefix="/analytics", tags=["analytics"])


setup_routers()
