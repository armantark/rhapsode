"""Replace the local database's application data with a Sites D1 export.

One-way sync, D1 → local, per memory-bank/handoffs/sites-data-sync.md: the
deployed site's practice progress is the truth, so the local rows are wiped
and rebuilt from the export produced by the temporary Worker route. The
local-only `gemini_api_key` setting survives (the D1 seed deliberately
excludes it), and `alembic_version` plus platform tables are untouched.

A manual snapshot is taken before any change. Plain sqlite3 is used instead
of the SQLAlchemy engine so the foreign_keys pragma genuinely applies (it is
a no-op inside a transaction, and the engine autobegins one).

Usage:
    uv run python scripts/import_d1_export.py ../work/d1-export
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from rhapsode.config import get_settings
from rhapsode.services.backup import snapshot_sqlite

SKIP_TABLES = {"__appgarden_migrations", "_cf_KV", "sqlite_sequence"}

# Insert order satisfies foreign keys read forward; deletes run reversed.
TABLE_ORDER = [
    "language_profiles",
    "passages",
    "passage_revisions",
    "segments",
    "annotations",
    "personal_notes",
    "collections",
    "collection_passages",
    "media_assets",
    "review_states",
    "practice_sessions",
    "practice_items",
    "attempts",
    "fsrs_review_logs",
    "plugin_manifests",
    "app_settings",
    "idempotency_records",
]


def _sqlite_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_dir", type=Path)
    args = parser.parse_args()
    tables_dir = args.export_dir / "tables"
    if not tables_dir.is_dir():
        raise SystemExit(f"No tables/ directory under {args.export_dir}.")

    settings = get_settings()
    database_path = settings.database_path()
    if database_path is None:
        raise SystemExit("This importer needs a file-backed SQLite database.")
    backup = snapshot_sqlite(
        database_path, settings.backup_dir / "manual", "pre-d1-import"
    )
    print(f"backup: {backup}")

    exports: dict[str, dict[str, Any]] = {}
    for path in tables_dir.glob("*.json"):
        payload = json.loads(path.read_text())
        name = payload.get("table") or path.stem
        if name not in SKIP_TABLES:
            exports[name] = payload
    missing = [name for name in TABLE_ORDER if name not in exports]
    if missing:
        raise SystemExit(f"Export is missing tables: {missing}")
    unexpected = set(exports) - set(TABLE_ORDER)
    if unexpected:
        raise SystemExit(f"Export has tables this importer does not know: {unexpected}")

    connection = sqlite3.connect(database_path)
    connection.isolation_level = None
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        gemini = connection.execute(
            "SELECT value FROM app_settings WHERE key = 'gemini_api_key'"
        ).fetchone()
        connection.execute("BEGIN")
        for name in reversed(TABLE_ORDER):
            connection.execute(f"DELETE FROM {name}")
        for name in TABLE_ORDER:
            rows = exports[name]["rows"]
            if not rows:
                continue
            local_columns = {
                row[1]
                for row in connection.execute(f"PRAGMA table_info({name})").fetchall()
            }
            columns = [column for column in rows[0].keys() if column in local_columns]
            dropped = set(rows[0].keys()) - set(columns)
            if dropped:
                print(f"{name}: ignoring D1-only columns {sorted(dropped)}")
            statement = (
                f"INSERT INTO {name} ({', '.join(columns)}) VALUES "
                f"({', '.join(':' + column for column in columns)})"
            )
            connection.executemany(
                statement,
                [
                    {column: _sqlite_value(row.get(column)) for column in columns}
                    for row in rows
                ],
            )
            print(f"{name}: {len(rows)} rows")
        if gemini is not None:
            connection.execute(
                "INSERT INTO app_settings (key, value) VALUES ('gemini_api_key', ?) "
                "ON CONFLICT(key) DO NOTHING",
                (gemini[0],),
            )
            print("app_settings: preserved local gemini_api_key")
        connection.execute("COMMIT")
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise SystemExit(f"Foreign key violations after import: {violations[:10]}")
        for name in TABLE_ORDER:
            declared = len(exports[name]["rows"])
            actual = connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            expected = declared + (
                1
                if name == "app_settings"
                and gemini is not None
                and not any(
                    row.get("key") == "gemini_api_key" for row in exports[name]["rows"]
                )
                else 0
            )
            if actual != expected:
                raise SystemExit(f"{name}: expected {expected} rows, found {actual}")
    finally:
        connection.close()
    print("import verified: counts match, no foreign key violations")


if __name__ == "__main__":
    main()
