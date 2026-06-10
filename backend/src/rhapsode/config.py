from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RHAPSODE_", extra="ignore")

    app_name: str = "Rhapsode"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("data")
    database_url: str = "sqlite:///data/rhapsode.db"
    media_dir: Path = Path("data/media")
    backup_dir: Path = Path("data/backups")
    desired_retention: float = 0.9

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
