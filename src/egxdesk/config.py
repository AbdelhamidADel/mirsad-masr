from __future__ import annotations

import json
from typing import Annotated, Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Provider keys for /v1 endpoints — user brings their own
    alpha_vantage_key: str = ""
    finnhub_key: str = ""

    # Operator-controlled keys used exclusively for the /demo endpoint
    demo_alpha_vantage_key: str = ""
    demo_finnhub_key: str = ""

    # Logging
    log_level: str = "info"
    dev_mode: bool = False  # pretty console output when True

    # Cache
    cache_ttl_seconds: int = 30
    demo_cache_ttl_seconds: int = 60
    cache_max_size: int = 512
    fetch_quotes_on_startup: bool = True
    auto_refresh_quotes: bool = True
    enable_yahoo_finance: bool = False

    # Demo rate limiting
    demo_daily_limit: int = 50

    # CORS
    cors_origins: Annotated[list[str], NoDecode] = ["*"]
    cors_origin_regex: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("["):
                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Email alerts (Postgres + mail). Off until DATABASE_URL + mail are set.
    # Prefer RESEND_API_KEY on Render free (SMTP ports 25/465/587 are blocked).
    alerts_enabled: bool = False
    database_url: str = ""
    resend_api_key: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    alerts_public_base_url: str = "http://127.0.0.1:8000"
    alerts_tick_secret: str = ""
    alerts_cooldown_hours_default: int = 6


settings = Settings()
