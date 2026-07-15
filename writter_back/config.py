"""Application configuration loaded from environment variables."""
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Novel Writer API"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1

    DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/novel_writer"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    JWT_SECRET: str = ""
    JWT_ISSUER: str = "novel-writer"
    JWT_AUDIENCE: str = "novel-writer-web"
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 30
    INVITATION_DAYS: int = 7
    DEFAULT_MONTHLY_GENERATION_LIMIT: int = 30
    PLATFORM_ADMIN_EMAIL: str | None = None
    PLATFORM_ADMIN_PASSWORD: str | None = None

    DEFAULT_LLM_PROVIDER: Literal["deepseek", "openai", "anthropic"] = "deepseek"
    DEFAULT_MODEL_NAME: str = "deepseek-chat"
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None
    OPENAI_MODEL: str = "gpt-4o"
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"
    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_MODEL: str = "deepseek-chat"
    LLM_TIMEOUT_SECONDS: float = 180.0
    WORKFLOW_TIMEOUT_SECONDS: float = 600.0
    SSE_HEARTBEAT_SECONDS: float = 15.0

    AGENT_MAX_CONTEXT_TOKENS: int = 128000
    MAX_TOOL_OUTPUT_CHARS: int = 10000
    MAX_REFLECTION_LOOPS: int = 3
    REFLECTION_THRESHOLD: float = 0.8
    MIN_CHAPTER_WORDS: int = 3000
    MAX_CHAPTER_WORDS: int = 6000
    LANGGRAPH_CHECKPOINTER_URI: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def selected_api_key(self) -> str | None:
        return {
            "deepseek": self.DEEPSEEK_API_KEY,
            "openai": self.OPENAI_API_KEY,
            "anthropic": self.ANTHROPIC_API_KEY,
        }[self.DEFAULT_LLM_PROVIDER]

    @model_validator(mode="after")
    def validate_limits(self) -> "Settings":
        if self.LLM_TIMEOUT_SECONDS <= 0 or self.WORKFLOW_TIMEOUT_SECONDS <= 0:
            raise ValueError("Timeout values must be positive")
        if self.ACCESS_TOKEN_MINUTES <= 0 or self.REFRESH_TOKEN_DAYS <= 0:
            raise ValueError("Token lifetime values must be positive")
        if self.ENVIRONMENT == "production" and len(self.JWT_SECRET) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 characters in production")
        return self


settings = Settings()
