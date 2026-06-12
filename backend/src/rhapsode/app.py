from collections.abc import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from rhapsode import __version__
from rhapsode.api.router import router
from rhapsode.config import get_settings
from rhapsode.database import Base, SessionLocal, engine
from rhapsode.idempotency import IdempotencyMiddleware
from rhapsode.seed import seed_defaults
from rhapsode.services.plugins import discover_entry_point_plugins


def create_app(
    session_factory: Callable[[], Session] = SessionLocal,
    *,
    create_tables: bool = True,
) -> FastAPI:
    app = FastAPI(
        title="Rhapsode API",
        version=__version__,
        description="Local-first API for structured oral memorization.",
    )
    app.state.session_factory = session_factory
    app.add_middleware(IdempotencyMiddleware)
    cors_origins = get_settings().resolved_cors_origins()
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(router)

    if create_tables:
        bind = session_factory.kw.get("bind") if hasattr(session_factory, "kw") else engine  # type: ignore[attr-defined]
        Base.metadata.create_all(bind=bind or engine)
        with session_factory() as db:
            seed_defaults(db)
    discover_entry_point_plugins()
    return app


app = create_app(create_tables=False)
