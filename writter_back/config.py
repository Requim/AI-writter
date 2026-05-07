"""Application configuration - centralized config management"""
import os
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file"""
    
    # ========= App =========
    APP_NAME: str = "Novel Writer API"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    
    # ========= Server =========
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1
    
    # ========= Database =========
    DATABASE_URL: str = "postgresql+asyncpg://postgres:mima12138@localhost:5432/novel_writer"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    
    # ========= Redis/Cache =========
    REDIS_URL: str = "redis://localhost:6379"
    
    # ========= JWT Auth =========
    JWT_SECRET_KEY: str = "your-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # ========= LLM =========
    DEFAULT_LLM_PROVIDER: str = "deepseek"  # openai, anthropic, deepseek
    DEFAULT_MODEL_NAME: str = "deepseek-v4-pro"
    
    # OpenAI
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o"
    
    # Anthropic
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"
    
    # DeepSeek
    DEEPSEEK_API_KEY: Optional[str] = "sk-ce93a5aa14ad48f0ae69ae205c6ef928"
    DEEPSEEK_MODEL: str = "deepseek-v4-pro"
    
    # ========= Agent Limits =========
    AGENT_MAX_CONTEXT_TOKENS: int = 128000
    MAX_TOOL_OUTPUT_CHARS: int = 10000
    MAX_REFLECTION_LOOPS: int = 3
    REFLECTION_THRESHOLD: float = 0.8
    
    # ========= Chapter Constraints =========
    MIN_CHAPTER_WORDS: int = 3000
    MAX_CHAPTER_WORDS: int = 6000
    
    # ========= LangGraph =========
    LANGGRAPH_CHECKPOINTER_URI: Optional[str] = None  # PostgresSaver URI
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Global settings instance
settings = Settings()
