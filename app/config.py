from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables or `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: SecretStr = Field(min_length=1)
    llm_model: str = "claude-sonnet-5-5"
    llm_timeout_s: float = Field(default=120.0, gt=0)
    llm_max_retries: int = Field(default=3, ge=0)
    llm_concurrency: int = Field(default=4, gt=0)
    chunk_timeout_s: float = Field(default=300.0, gt=0)  # whole chunk, including retries
    llm_effort: Literal["low", "medium", "high"] = "medium"

    database_url: str = "sqlite:///./data/app.db"

    max_upload_mb: int = Field(default=20, gt=0)
    max_pages: int = Field(default=300, gt=0)
    chunk_chars: int = Field(default=40_000, ge=1_000)
    min_chars_per_page: int = Field(default=50, ge=0)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
