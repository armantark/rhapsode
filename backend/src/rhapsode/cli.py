import uvicorn

from rhapsode.config import get_settings
from rhapsode.database import SessionLocal
from rhapsode.migrations import main as migrate
from rhapsode.seed import seed_defaults


def main() -> None:
    settings = get_settings()
    migrate()
    with SessionLocal() as db:
        seed_defaults(db)
    uvicorn.run("rhapsode.app:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
