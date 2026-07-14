"""Attach source references to one active passage and refresh its open chains.

Source references are display metadata. This utility deliberately leaves line
ordinals, text, review states, and completed practice items unchanged.

Usage:
    uv run python scripts/backfill_source_references.py \
        --title "Iliad 6-7" \
        --passage-reference "Iliad 1.6–7" \
        --line-reference "Iliad 1.6" \
        --line-reference "Iliad 1.7"
"""

from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from rhapsode import models
from rhapsode.database import SessionLocal
from rhapsode.services import planning


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--passage-reference", required=True)
    parser.add_argument("--line-reference", action="append", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db:
        revision = _load_active_revision(db, args.title)
        lines = sorted(
            (segment for segment in revision.segments if segment.kind == "line"),
            key=lambda segment: segment.ordinal,
        )
        if len(lines) != len(args.line_reference):
            raise SystemExit(
                f"Expected {len(lines)} --line-reference values, got {len(args.line_reference)}."
            )

        revision.reference_label = args.passage_reference
        for line, reference in zip(lines, args.line_reference, strict=True):
            line.reference_label = reference
        refreshed = _refresh_active_chains(db, revision)

        if args.dry_run:
            db.rollback()
            action = "would backfill"
        else:
            db.commit()
            action = "backfilled"
        print(
            f"{revision.id}: {action} {args.passage_reference} across {len(lines)} lines; "
            f"refreshed {refreshed} active chaining prompts"
        )


def _load_active_revision(db: Session, title: str) -> models.PassageRevision:
    revision = db.scalar(
        select(models.PassageRevision)
        .join(models.Passage)
        .where(models.Passage.title == title)
        .where(models.Passage.active_revision_id == models.PassageRevision.id)
        .options(
            joinedload(models.PassageRevision.passage),
            selectinload(models.PassageRevision.segments),
        )
    )
    if revision is None:
        raise SystemExit(f'No active passage titled "{title}".')
    return revision


def _refresh_active_chains(db: Session, revision: models.PassageRevision) -> int:
    line_numbers = planning._line_number_map(planning._ordered_segments(revision, None))
    segments_by_id = {segment.id: segment for segment in revision.segments}
    items = db.scalars(
        select(models.PracticeItem)
        .join(models.PracticeSession)
        .where(models.PracticeItem.revision_id == revision.id)
        .where(models.PracticeItem.completed.is_(False))
        .where(models.PracticeSession.status == "active")
        .where(
            models.PracticeItem.mode.in_({"forward_chaining", "backward_chaining"})
        )
    )
    refreshed = 0
    for item in items:
        chain_ids = item.prompt.get("chain_segment_ids", [])
        context = [
            segments_by_id[segment_id]
            for segment_id in chain_ids
            if segment_id in segments_by_id
        ]
        if not context:
            continue
        item.prompt = planning._chain_prompt(
            context,
            [line_numbers[segment.id] for segment in context],
        )
        refreshed += 1
    return refreshed


if __name__ == "__main__":
    main()
