"""SQLite snapshot backups.

Two triggers, decided in the 2026-06-10 grill (D1): an unconditional copy
before migrations (schema changes are the riskiest moment), and a startup
snapshot gated to once per 24h (startup is a quiet-db moment and needs no
scheduler for a single-user interactive app). Retention is bounded so the
backup dir can live in a synced folder without growing forever.
"""

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

SNAPSHOT_RETENTION = 14
STARTUP_SNAPSHOT_MIN_AGE = timedelta(hours=24)


def snapshot_sqlite(database_path: Path, backup_dir: Path, label: str) -> Path | None:
    if not database_path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination = (
        backup_dir / f"{database_path.stem}-{label}-{timestamp}{database_path.suffix}"
    )
    shutil.copy2(database_path, destination)
    _prune(backup_dir, database_path)
    return destination


def startup_snapshot(database_path: Path, backup_dir: Path) -> Path | None:
    newest = _newest_snapshot_mtime(backup_dir, database_path)
    if newest is not None and datetime.now(UTC) - newest < STARTUP_SNAPSHOT_MIN_AGE:
        return None
    return snapshot_sqlite(database_path, backup_dir, "startup")


def newest_snapshot_at(database_path: Path, backup_dir: Path) -> datetime | None:
    """When the last snapshot landed — the settings screen's backup-health line."""
    return _newest_snapshot_mtime(backup_dir, database_path)


def _snapshots(backup_dir: Path, database_path: Path) -> list[Path]:
    if not backup_dir.exists():
        return []
    pattern = f"{database_path.stem}-*{database_path.suffix}"
    return sorted(backup_dir.glob(pattern), key=lambda path: path.stat().st_mtime)


def _newest_snapshot_mtime(backup_dir: Path, database_path: Path) -> datetime | None:
    snapshots = _snapshots(backup_dir, database_path)
    if not snapshots:
        return None
    return datetime.fromtimestamp(snapshots[-1].stat().st_mtime, tz=UTC)


def _prune(backup_dir: Path, database_path: Path) -> None:
    snapshots = _snapshots(backup_dir, database_path)
    for stale in snapshots[:-SNAPSHOT_RETENTION]:
        stale.unlink(missing_ok=True)
