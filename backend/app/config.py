"""Application configuration.

All settings are loaded from environment variables (optionally from a local
`.env` file). Never commit real credentials; use `.env.example` as template.
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """WeatherGPT application settings."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Application ---
    app_env: str = "development"
    app_name: str = "WeatherGPT"
    debug: bool = True
    api_title: str = "WeatherGPT API"
    api_version: str = "0.1.0"

    # --- CORS ---
    cors_origins: list[str] = ["*"]  # restrict in production

    # --- Weather provider ---
    # --- Weather provider ---
    # Default is Open-Meteo (free, no key required for non-commercial use).
    # Set WEATHER_API_BASE_URL to OpenWeather's 2.5 API and WEATHER_API_KEY
    # to use OpenWeather for current conditions and the 5-day forecast:
    #   https://api.openweathermap.org/data/2.5
    #   Weather Forecast API  → https://api.open-meteo.com/v1/forecast
#   Geocoding API         → https://geocoding-api.open-meteo.com/v1/search
    weather_api_key: Optional[str] = None
    weather_api_base_url: str = "https://api.open-meteo.com/v1"
    geocoding_api_base_url: str = "https://geocoding-api.open-meteo.com/v1"
    weather_timeout_seconds: float = 10.0

    # --- LLM provider (LangChain + Google Gemini Flash) ---
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-1.5-flash"
    llm_timeout_seconds: float = 30.0
    llm_max_history_messages: int = 8

    # --- Cache (Redis) ---
    redis_url: str = "redis://localhost:6379/0"
    cache_current_ttl_seconds: int = 600  # 5-15 min per technical.md
    cache_forecast_ttl_seconds: int = 1800  # 30-60 min
    cache_geocode_ttl_seconds: int = 21600  # several hours
    cache_historical_ttl_seconds: int = 3600  # past observations are immutable per day
    cache_climate_ttl_seconds: int = 86400  # climate trends are recomputed rarely

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./weathergpt.db"

    # --- Auth ---
    jwt_secret: str = "change_this_in_production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7

    # --- Rate limiting (simple per-process limiter) ---
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    chat_rate_limit_requests: int = 10
    chat_rate_limit_window_seconds: int = 60

    # --- Provider rate-limit mitigation ---
    # When the weather provider returns 429 (too many requests), serve the
    # best available cached/stale payload instead of failing the request.
    serve_stale_on_provider_rate_limit: bool = True
    # Do not immediately retry Open-Meteo after it has sent a 429 response.
    weather_rate_limit_cooldown_seconds: int = 60

    # --- Alerts ---
    alert_scheduler_enabled: bool = False
    alert_check_interval_seconds: int = 900

    # --- Firebase (notifications) ---
    firebase_project_id: Optional[str] = None
    # Service-account JSON inline or a file path; enables real FCM delivery.
    firebase_service_account_json: Optional[str] = None

    # --- RAG ---
    rag_enabled: bool = False
    chroma_dir: str = "./chroma_db"
    rag_chunk_size: int = 1000
    rag_chunk_overlap: int = 150
    rag_top_k: int = 3


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


settings = get_settings()
