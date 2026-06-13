from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "DSE Meli Sync"
    VERSION: str = "1.0.0"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/dse_meli_sync"

    # Celery & Redis
    CELERY_BROKER_URL: str = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/0"

    # Security & Cryptography
    PROMPT_DECRYPTION_KEY: str = ""
    MASTER_PROMPT_ENCRYPTED: str = ""

    # Mercado Livre
    MELI_CLIENT_ID: Optional[str] = None
    MELI_CLIENT_SECRET: Optional[str] = None
    MELI_WEBHOOK_SIGNATURE_KEY: Optional[str] = None

    # LLM Settings
    LLM_PROVIDER: str = "gemini"
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gemini-1.5-flash"

    # Config options to load from .env file
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
