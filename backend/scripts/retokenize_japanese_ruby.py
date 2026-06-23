"""Retokenize Japanese ruby support for old revisions.

New Japanese revisions already get local fugashi/UniDic token children and ruby
readings during creation. This script repairs revisions created under older
contracts, including generated junctures that did not previously receive token
children.

Usage:
    uv run python scripts/retokenize_japanese_ruby.py --title "Sono Chi no Sadame"
    uv run python scripts/retokenize_japanese_ruby.py --revision-id REVISION_ID
    uv run python scripts/retokenize_japanese_ruby.py --title "..." --dry-run
"""

from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from rhapsode import models
from rhapsode.database import SessionLocal
from rhapsode.services import passages
from rhapsode.services.furigana import retokenize_revision


def main() -> None:
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--revision-id")
    target.add_argument("--title")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db:
        revision = _load_revision(db, revision_id=args.revision_id, title=args.title)
        junctures = passages.refresh_junctures(db, revision)
        stats = retokenize_revision(db, revision)
        if args.dry_run:
            db.rollback()
            action = "would retokenize"
        else:
            db.commit()
            action = "retokenized"
        print(
            f"{revision.id}: {action} {stats['targets']} targets, "
            f"deleted {stats['deleted']} tokens, created {stats['created']} tokens, "
            f"wrote {stats['readings']} readings, "
            f"refreshed {junctures['updated']} junctures"
        )


def _load_revision(
    db: Session, *, revision_id: str | None, title: str | None
) -> models.PassageRevision:
    query = select(models.PassageRevision).options(
        joinedload(models.PassageRevision.passage).joinedload(models.Passage.language_profile),
        selectinload(models.PassageRevision.segments).selectinload(models.Segment.annotations),
    )
    if revision_id:
        query = query.where(models.PassageRevision.id == revision_id)
    else:
        query = (
            query.join(models.Passage)
            .where(models.Passage.title == title)
            .where(models.Passage.active_revision_id == models.PassageRevision.id)
        )
    revision = db.scalar(query)
    if revision is None:
        raise SystemExit("No matching revision.")
    return revision


if __name__ == "__main__":
    main()
