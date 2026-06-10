from pathlib import Path

from alembic import command
from alembic.config import Config
from rhapsode.config import get_settings
from rhapsode.services.media import snapshot_sqlite


def database_path(database_url: str) -> Path | None:
    prefix = "sqlite:///"
    return Path(database_url.removeprefix(prefix)) if database_url.startswith(prefix) else None


def main() -> None:
    settings = get_settings()
    path = database_path(settings.database_url)
    if path:
        snapshot_sqlite(path, settings.backup_dir)
    config = Config("alembic.ini")
    config.attributes["database_url"] = settings.database_url
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
