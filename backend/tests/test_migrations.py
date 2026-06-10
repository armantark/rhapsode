import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config

INITIAL_REVISION = "9306b49e8942"


def migration_config(database_path: Path) -> Config:
    config = Config("alembic.ini")
    database_url = f"sqlite:///{database_path}"
    config.attributes["database_url"] = database_url
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_cue_point_migration_preserves_existing_media(tmp_path: Path) -> None:
    database_path = tmp_path / "rhapsode.db"
    config = migration_config(database_path)
    command.upgrade(config, INITIAL_REVISION)

    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO media_assets (
                id, revision_id, segment_id, category, mime_type, original_name,
                storage_path, size_bytes, created_at, updated_at
            ) VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "existing-media",
                "reference",
                "audio/mp4",
                "existing.m4a",
                "/tmp/existing.m4a",
                42,
                now,
                now,
            ),
        )

    command.upgrade(config, "head")

    with sqlite3.connect(database_path) as connection:
        cue_points = connection.execute(
            "SELECT cue_points FROM media_assets WHERE id = ?", ("existing-media",)
        ).fetchone()
    assert cue_points is not None
    assert json.loads(cue_points[0]) == []
