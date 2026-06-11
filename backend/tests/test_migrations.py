import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config

INITIAL_REVISION = "9306b49e8942"
PRE_COLLECTION_REVISION = "a1f2c3d4e5f6"


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


def test_collection_migration_backfills_practice_item_revision(tmp_path: Path) -> None:
    database_path = tmp_path / "rhapsode.db"
    config = migration_config(database_path)
    command.upgrade(config, PRE_COLLECTION_REVISION)

    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO language_profiles (
                id, slug, name, direction, fonts, annotation_schemas,
                segmentation_defaults, display_options, created_at, updated_at
            ) VALUES ('language', 'latin', 'Latin', 'ltr', '[]', '[]', '{}', '{}', ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO passages (
                id, title, language_profile_id, description, active_revision_id,
                created_at, updated_at
            ) VALUES ('passage', 'Aeneid', 'language', NULL, 'revision', ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO passage_revisions (
                id, passage_id, revision_number, source_text, hierarchy, practiced,
                created_at, updated_at
            ) VALUES ('revision', 'passage', 1, 'arma', '{}', 1, ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO practice_sessions (
                id, revision_id, status, plan, current_index, completed_at,
                created_at, updated_at
            ) VALUES ('session', 'revision', 'active', '{}', 0, NULL, ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO segments (
                id, revision_id, parent_id, kind, ordinal, text, cue, metadata_json,
                created_at, updated_at
            ) VALUES ('segment', 'revision', NULL, 'line', 0, 'arma', NULL, '{}', ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO practice_items (
                id, session_id, segment_id, position, mode, prompt, completed,
                created_at, updated_at
            ) VALUES ('item', 'session', 'segment', 0, 'cue_recall', '{}', 0, ?, ?)
            """,
            (now, now),
        )

    command.upgrade(config, "head")

    with sqlite3.connect(database_path) as connection:
        item_revision = connection.execute(
            "SELECT revision_id FROM practice_items WHERE id = 'item'"
        ).fetchone()
        session_columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(practice_sessions)")
        }
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert item_revision == ("revision",)
    assert session_columns["revision_id"][3] == 0
    assert "collection_id" in session_columns
    assert {"collections", "collection_passages"} <= tables
