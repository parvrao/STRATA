from pydantic_settings import BaseSettings
from typing import List
import secrets


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "postgresql://strata:password@localhost:5432/strata_db"
    REDIS_URL: str = ""

    # Auth
    SECRET_KEY: str = secrets.token_urlsafe(64)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ── Google Gemini (free) ──────────────────────────────
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"   # free tier model
    GEMINI_MAX_TOKENS: int = 2000

    # Token budgets per plan
    FREE_TIER_MONTHLY_TOKENS: int = 100_000
    BUILD_TIER_MONTHLY_TOKENS: int = 1_000_000
    SCALE_TIER_MONTHLY_TOKENS: int = 5_000_000

    # Stripe — all optional for demo
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_BUILD_MONTHLY: str = ""
    STRIPE_PRICE_FUNDRAISE_MONTHLY: str = ""
    STRIPE_PRICE_GROWTH_MONTHLY: str = ""
    STRIPE_PRICE_SCALE_PLUS_MONTHLY: str = ""
    STRIPE_PRICE_ENTERPRISE_MONTHLY: str = ""
    STRIPE_PRICE_COMMAND_MONTHLY: str = ""

    # Email — optional
    EMAIL_PROVIDER: str = "resend"
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@strata.ai"
    EMAIL_FROM_NAME: str = "STRATA"

    CORS_ORIGINS: List[str] = ["*"]
    ALLOWED_HOSTS: List[str] = ["*"]

    RATE_LIMIT_AUTH: int = 20
    RATE_LIMIT_AI: int = 60
    RATE_LIMIT_GLOBAL: int = 500

    ADMIN_EMAIL: str = ""
    CALCOM_API_KEY: str = ""
    CALCOM_BASE_URL: str = "https://api.cal.com/v1"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
