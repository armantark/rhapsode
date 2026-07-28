"""Stitch several passages into one, in order, keeping all learning history.

A work that grows in batches belongs in one passage: the runway then spans
the whole text and junctures generate at every boundary, including the former
passage seams. This is the one-time repair for material that accumulated as
separate passages (the piecemeal Iliad batches); future additions should use
the passage page's "+ Add lines" append instead of new passages.

The first argument is the HOST passage — its segments and states are left
untouched, and everything else is appended after it in the order given.
A manual database snapshot is taken before any change.

Usage:
    uv run python scripts/merge_passages.py HOST_ID SOURCE_ID [SOURCE_ID ...] \
        [--title "Iliad 1"] [--reference-label "Iliad 1.1-20"]
"""

from __future__ import annotations

import argparse

from rhapsode import models
from rhapsode.config import get_settings
from rhapsode.database import SessionLocal
from rhapsode.services.backup import snapshot_sqlite
from rhapsode.services.passages import merge_passages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host_id")
    parser.add_argument("source_ids", nargs="+")
    parser.add_argument("--title", help="New title for the merged host passage.")
    parser.add_argument(
        "--reference-label", help="New reference label for the host's active revision."
    )
    args = parser.parse_args()

    settings = get_settings()
    database_path = settings.database_path()
    if database_path is not None:
        backup = snapshot_sqlite(
            database_path, settings.backup_dir / "manual", "pre-merge"
        )
        print(f"backup: {backup}")

    with SessionLocal() as db:
        host = db.get(models.Passage, args.host_id)
        if host is None:
            raise SystemExit(f"Host passage {args.host_id} not found.")
        sources = []
        for source_id in args.source_ids:
            source = db.get(models.Passage, source_id)
            if source is None:
                raise SystemExit(f"Source passage {source_id} not found.")
            sources.append(source)
        moved = merge_passages(db, host, sources)
        if args.title:
            host.title = args.title
        if args.reference_label and host.active_revision_id:
            revision = db.get(models.PassageRevision, host.active_revision_id)
            if revision is not None:
                revision.reference_label = args.reference_label
        db.commit()
        print(
            f"merged {len(sources)} passages into {host.title}: "
            f"{moved['lines']} lines, {moved['junctures']} junctures, "
            f"{moved['states']} review states, {moved['attempts']} attempts, "
            f"{moved['media']} media assets moved"
        )


if __name__ == "__main__":
    main()
