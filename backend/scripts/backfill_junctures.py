"""Backfill juncture segments onto revisions created before junctures existed.

New revisions get junctures automatically in add_segments; this script covers
already-practiced revisions, which segment replacement (correctly) refuses to
touch. Junctures don't alter the recall target, so direct insertion is safe —
the same reasoning that exempted annotations from revision immutability.

Idempotent: add_junctures skips line pairs that already have one.

Usage:
    uv run python scripts/backfill_junctures.py            # all revisions
    uv run python scripts/backfill_junctures.py REVISION_ID
"""

import sys

from sqlalchemy import select

from rhapsode import models
from rhapsode.database import SessionLocal
from rhapsode.services.passages import add_junctures


def main() -> None:
    revision_id = sys.argv[1] if len(sys.argv) > 1 else None
    with SessionLocal() as db:
        query = select(models.PassageRevision)
        if revision_id:
            query = query.where(models.PassageRevision.id == revision_id)
        revisions = list(db.scalars(query))
        if not revisions:
            raise SystemExit("No matching revisions.")
        for revision in revisions:
            created = add_junctures(db, revision.id, list(revision.segments))
            print(f"{revision.id}: +{len(created)} junctures")
        db.commit()


if __name__ == "__main__":
    main()
