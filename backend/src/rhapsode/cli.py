import uvicorn

from rhapsode.config import get_settings
from rhapsode.database import SessionLocal
from rhapsode.migrations import database_path
from rhapsode.migrations import main as migrate
from rhapsode.seed import seed_defaults
from rhapsode.services.backup import startup_snapshot


def main() -> None:
    settings = get_settings()
    migrate()
    db_path = database_path(settings.database_url)
    if db_path:
        startup_snapshot(db_path, settings.backup_dir)
    with SessionLocal() as db:
        seed_defaults(db)
    uvicorn.run("rhapsode.app:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
