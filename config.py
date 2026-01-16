"""Configuration settings for Tavily Search Analytics Service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Keys
    tavily_api_key: str = ""
    openai_api_key: str = ""

    # Tavily API settings
    tavily_api_url: str = "https://api.tavily.com/search"

    # Service ports
    main_service_port: int = 8000
    enricher_service_port: int = 8001
    enricher_service_url: str = "http://localhost:8001"

    # Database
    database_path: str = "analytics.db"

    # Cache settings
    cache_ttl_seconds: int = 86400  # 24 hours
    snippet_max_length: int = 200

    # Retry settings
    max_retries: int = 5
    retry_base_delay_seconds: float = 1.0  # Exponential backoff: 1s, 2s, 4s, 8s, 16s

    # Enricher settings
    enricher_failure_rate: float = 0.3  # 30% failure rate for testing
    enricher_delay_seconds: float = 0.1  # Simulated processing delay

    # LLM settings
    openai_model: str = "gpt-4o-mini"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


# Global settings instance
settings = Settings()
