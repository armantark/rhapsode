from __future__ import annotations

import shutil
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from rhapsode.app import create_app
from rhapsode.config import clear_settings_cache, get_settings
from rhapsode.desktop import DEFAULT_DESKTOP_CORS_ORIGINS
from rhapsode.resources import (
    alembic_ini_path,
    alembic_script_dir,
    backend_root,
    build_alembic_config,
)


@pytest.fixture(autouse=True)
def reset_settings_cache() -> Generator[None]:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_runtime_env_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "app-data"
    media_dir = data_dir / "media"
    backup_dir = data_dir / "backups"
    database_path = data_dir / "rhapsode.db"
    monkeypatch.setenv("RHAPSODE_PORT", "9123")
    monkeypatch.setenv("RHAPSODE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("RHAPSODE_DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("RHAPSODE_MEDIA_DIR", str(media_dir))
    monkeypatch.setenv("RHAPSODE_BACKUP_DIR", str(backup_dir))

    settings = get_settings()

    assert settings.port == 9123
    assert settings.data_dir == data_dir
    assert settings.database_url == f"sqlite:///{database_path}"
    assert settings.media_dir == media_dir
    assert settings.backup_dir == backup_dir
    assert database_path.parent.exists()
    assert media_dir.exists()
    assert backup_dir.exists()


def test_dev_alembic_resources_resolve_from_backend_root() -> None:
    root = backend_root()
    assert (root / "alembic.ini").exists()
    assert alembic_ini_path().name == "alembic.ini"
    assert alembic_script_dir().name == "alembic"
    assert (alembic_script_dir() / "env.py").exists()


def test_frozen_alembic_resources_use_meipass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    backend = Path(__file__).resolve().parents[1]
    shutil.copytree(backend / "alembic", bundle / "alembic")
    shutil.copy2(backend / "alembic.ini", bundle / "alembic.ini")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)

    assert backend_root() == bundle
    config = build_alembic_config(f"sqlite:///{tmp_path / 'frozen.db'}")
    assert config.get_main_option("script_location") == str(bundle / "alembic")


def test_browser_mode_has_no_cors_headers(session_factory: sessionmaker[Session]) -> None:
    with TestClient(create_app(session_factory)) as client:
        response = client.get(
            "/api/v1/health",
            headers={"Origin": "http://localhost:5173"},
        )
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_desktop_mode_allows_tauri_origin(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    monkeypatch.setenv("RHAPSODE_DESKTOP", "1")
    clear_settings_cache()

    with TestClient(create_app(session_factory)) as client:
        preflight = client.options(
            "/api/v1/health",
            headers={
                "Origin": "tauri://localhost",
                "Access-Control-Request-Method": "GET",
            },
        )
        response = client.get("/api/v1/health", headers={"Origin": "tauri://localhost"})

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "tauri://localhost"
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"


def test_desktop_cors_defaults_match_handoff() -> None:
    assert "tauri://localhost" in DEFAULT_DESKTOP_CORS_ORIGINS
    assert "https://tauri.localhost" in DEFAULT_DESKTOP_CORS_ORIGINS


def test_custom_cors_origins_override_defaults(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    monkeypatch.setenv("RHAPSODE_DESKTOP", "1")
    monkeypatch.setenv("RHAPSODE_CORS_ORIGINS", "https://example.test")
    clear_settings_cache()

    with TestClient(create_app(session_factory)) as client:
        response = client.get("/api/v1/health", headers={"Origin": "https://example.test"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://example.test"
