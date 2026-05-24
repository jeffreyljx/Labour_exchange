from __future__ import annotations

import json
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings

_INSECURE_DEFAULT = "change-me-in-production-dev-secret"


class Settings(BaseSettings):
    # Local prototype default: a SQLite file so the app can run in a browser
    # without Docker/Postgres setup. Set DATABASE_URL to PostgreSQL for deploys.
    database_url: str = "sqlite:///./hce_dev.db"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = _INSECURE_DEFAULT
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours
    dev_auth_enabled: bool = True
    auto_create_tables: bool = True

    # Explicit origin list; localhost:3000 is kept for local frontend dev.
    # In production, set CORS_ORIGINS="https://your-app.vercel.app" in the environment.
    cors_origins: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:8081",
        "http://127.0.0.1:8081",
        "http://localhost:19006",
        "http://127.0.0.1:19006",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
            except json.JSONDecodeError:
                parsed = [origin.strip() for origin in v.split(",")]
            if isinstance(parsed, str):
                parsed = [parsed]
            return [origin for origin in parsed if origin]
        return v

    @field_validator("secret_key")
    @classmethod
    def secret_key_must_be_strong(cls, v: str) -> str:
        if v == _INSECURE_DEFAULT:
            import warnings
            warnings.warn(
                "SECRET_KEY is still the insecure default. "
                "Set a strong SECRET_KEY environment variable before any production deploy.",
                stacklevel=2,
            )
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long.")
        return v

    # Exchange constants
    shares_per_contract: int = 1000
    max_income_pct_per_issuer: float = 49.0
    min_credit_score: int = 600

    # Settlement / reporting constants
    report_period_days: int = 91        # ~quarterly; days per reporting period
    report_due_grace_days: int = 30     # days after period_end before OVERDUE
    overdue_reputation_penalty: float = 10.0   # points lost per missed report

    # Reputation constants
    late_report_penalty: float = 5.0           # points lost for a late (but submitted) report
    on_time_report_bonus: float = 2.0          # points gained for an on-time report
    default_reputation_penalty: float = 30.0   # points lost when a contract defaults
    default_consecutive_threshold: int = 2     # consecutive OVERDUE periods to trigger DEFAULT

    model_config = {"env_file": ".env"}


settings = Settings()
