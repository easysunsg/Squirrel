import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Squirrel Service"
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: Path = Path("../data")
    storage_dir: Path = Path("../storage")
    ai_provider: str = "mock"
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ai_timeout: float = 60.0
    chroma_enabled: bool = True

    model_config = SettingsConfigDict(
        env_prefix="SQUIRREL_",
        env_file=".env",
        extra="ignore",
    )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "squirrel.sqlite3"

    @property
    def markdown_path(self) -> Path:
        return self.storage_dir / "inventory.md"

    @property
    def chroma_path(self) -> Path:
        return self.data_dir / "chroma"


settings = Settings()

settings.ai_provider = os.getenv("AI_PROVIDER", settings.ai_provider)
settings.ai_base_url = os.getenv("AI_BASE_URL", settings.ai_base_url)
settings.ai_api_key = os.getenv("AI_API_KEY", settings.ai_api_key)
settings.ai_model = os.getenv("AI_MODEL", settings.ai_model)
settings.ai_timeout = float(os.getenv("AI_TIMEOUT", settings.ai_timeout))
