from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from rhapsode.desktop import DEFAULT_DESKTOP_CORS_ORIGINS


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
    # Set by the Tauri host when spawning the sidecar so loopback CORS is enabled.
    desktop: bool = False
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    desired_retention: float = 0.9
    # Prep assistant (grill C1/C2): Gemini 3.1 Pro is Arman's explicit model
    # choice; do not change it without his say-so. The -preview suffix is the
    # only identifier the API exposes for 3.1 Pro right now.
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    gemini_model: str = "gemini-3.1-pro-preview"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        if isinstance(value, list):
            return [str(origin) for origin in value]
        msg = "cors_origins must be a comma-separated string or list of strings"
        raise TypeError(msg)

    def resolved_cors_origins(self) -> list[str]:
        if self.cors_origins:
            return self.cors_origins
        if self.desktop:
            return list(DEFAULT_DESKTOP_CORS_ORIGINS)
        return []

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        db_path = self.database_path()
        if db_path is not None:
            db_path.parent.mkdir(parents=True, exist_ok=True)

    def database_path(self) -> Path | None:
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            return Path(self.database_url.removeprefix(prefix))
        return None


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings


def clear_settings_cache() -> None:
    get_settings.cache_clear()
