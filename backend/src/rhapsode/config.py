from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RHAPSODE_",
        # The shared key lives in the repo-root .env; backend runs from backend/.
        env_file=("../.env", ".env"),
        extra="ignore",
    )

    app_name: str = "Rhapsode"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("data")
    database_url: str = "sqlite:///data/rhapsode.db"
    media_dir: Path = Path("data/media")
    backup_dir: Path = Path("data/backups")
    desired_retention: float = 0.9
    # Prep assistant (grill C1/C2): Gemini 3.1 Pro is Arman's explicit model
    # choice; do not change it without his say-so. The -preview suffix is the
    # only identifier the API exposes for 3.1 Pro right now.
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    gemini_model: str = "gemini-3.1-pro-preview"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
