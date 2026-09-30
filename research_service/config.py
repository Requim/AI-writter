"""研究服务配置；密钥只从环境变量读取。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "Novel Research Service"
    environment: str = "development"
    host: str = "0.0.0.0"
    port: int = 8010
    root_path: str = ""
    database_url: str = ""
    internal_token: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    summary_model: str = ""
    opening_authorized: bool = False
    max_requests: int = 200
    min_interval_seconds: float = 1.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="RESEARCH_",
        extra="ignore",
    )


settings = Settings()
