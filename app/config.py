"""Environment-based application configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_api_key: str = ""
    llm_model: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    request_timeout_seconds: float = 8.0
    llm_max_attempts: int = 2
    llm_retry_base_seconds: float = 0.25


settings = Settings()
