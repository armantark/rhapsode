"""Resolve bundled resources for dev installs and PyInstaller sidecars."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic.config import Config


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def backend_root() -> Path:
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2]


def alembic_ini_path() -> Path:
    return backend_root() / "alembic.ini"


def alembic_script_dir() -> Path:
    return backend_root() / "alembic"


def build_alembic_config(database_url: str) -> Config:
    config = Config(str(alembic_ini_path()))
    config.set_main_option("script_location", str(alembic_script_dir()))
    config.attributes["database_url"] = database_url
    config.set_main_option("sqlalchemy.url", database_url)
    return config
