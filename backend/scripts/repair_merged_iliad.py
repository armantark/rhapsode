"""One-time repair for the merged Iliad 1 passage (2026-07-28).

Two data defects rode into the merge:

1. Word-soup tokens: merge_passages appended source token children with
   unshifted ordinals, so add_segments (which sorts by ordinal) created them
   before their shifted parent lines existed and orphaned them to the top
   level. The reading view rendered them as vertical word stacks. The code
   bug is fixed in merge_passages; this repairs the data by deleting the
   orphans and recopying token subtrees from the intact source revisions.

2. Unearned mastery: the old Sites Worker never implemented guided-ladder
   step progression (zero guided_recall attempts exist in the imported
   history), so every acquired line arrived with learning_step NULL and the
   runway gate read it as mastered. Per Arman's ruling, Iliad 1.1-1.8 stay
   mastered and 1.9-1.12 re-enter the ladder at half-word cues (step 3).

Takes a manual snapshot first. Safe to re-run: no orphans means no token
work, and the demotion is idempotent.

Usage:
    uv run python scripts/repair_merged_iliad.py
"""

from __future__ import annotations

from sqlalchemy import select

from rhapsode import models
from rhapsode.config import get_settings
from rhapsode.database import SessionLocal
from rhapsode.services import planning
from rhapsode.services.backup import snapshot_sqlite

SOURCE_TITLES = ["Iliad 6-7", "Iliad 8-10", "Iliad 11-20"]
HOST_LINE_COUNT = 5
REOPEN = {"Iliad 1.9", "Iliad 1.10", "Iliad 1.11", "Iliad 1.12"}
HALF_WORD_CUES_STEP = 3


def main() -> None:
    settings = get_settings()
    database_path = settings.database_path()
    if database_path is not None:
        backup = snapshot_sqlite(
            database_path, settings.backup_dir / "manual", "pre-token-repair"
        )
        print(f"backup: {backup}")

    with SessionLocal() as db:
        host = db.scalar(select(models.Passage).where(models.Passage.title == "Iliad 1"))
        if host is None or host.active_revision_id is None:
            raise SystemExit("Merged passage 'Iliad 1' not found.")
        merged = db.get(models.PassageRevision, host.active_revision_id)
        assert merged is not None
        merged_lines = sorted(
            (s for s in merged.segments if s.kind == "line"), key=lambda s: s.ordinal
        )

        orphans = [
            s for s in merged.segments if s.kind == "token" and s.parent_id is None
        ]
        for orphan in orphans:
            db.delete(orphan)
        db.flush()
        print(f"deleted {len(orphans)} orphan tokens")

        recreated = 0
        if orphans:
            cursor = HOST_LINE_COUNT
            for title in SOURCE_TITLES:
                source = db.scalar(
                    select(models.Passage).where(models.Passage.title == title)
                )
                assert source is not None and source.active_revision_id is not None
                revision = db.get(models.PassageRevision, source.active_revision_id)
                assert revision is not None
                lines = sorted(
                    (s for s in revision.segments if s.kind == "line"),
                    key=lambda s: s.ordinal,
                )
                children_by_parent: dict[str, list[models.Segment]] = {}
                for segment in revision.segments:
                    if segment.kind == "token" and segment.parent_id is not None:
                        children_by_parent.setdefault(segment.parent_id, []).append(
                            segment
                        )
                for line in lines:
                    target = merged_lines[cursor]
                    if target.text != line.text:
                        raise SystemExit(
                            f"Line mismatch at position {cursor}: "
                            f"{target.text!r} != {line.text!r}"
                        )
                    for token in sorted(
                        children_by_parent.get(line.id, []), key=lambda s: s.ordinal
                    ):
                        clone = models.Segment(
                            revision_id=merged.id,
                            parent_id=target.id,
                            kind="token",
                            ordinal=token.ordinal + target.ordinal - line.ordinal,
                            text=token.text,
                            reference_label=token.reference_label,
                            cue=token.cue,
                            metadata_json=token.metadata_json or {},
                        )
                        db.add(clone)
                        db.flush()
                        for annotation in token.annotations:
                            db.add(
                                models.Annotation(
                                    segment_id=clone.id,
                                    layer=annotation.layer,
                                    value=annotation.value,
                                    data=annotation.data,
                                )
                            )
                        recreated += 1
                    cursor += 1
        print(f"recreated {recreated} parented tokens")

        reopened = []
        for line in merged_lines:
            if line.reference_label in REOPEN:
                state = db.scalar(
                    select(models.ReviewState).where(
                        models.ReviewState.segment_id == line.id
                    )
                )
                if state is None:
                    continue
                state.learning_step = HALF_WORD_CUES_STEP
                state.learning_success_count = 0
                state.mastery_stage = "learning"
                reopened.append(line.reference_label)
        print(f"reopened ladder at half-word cues: {reopened}")
        db.commit()

        db.expire_all()
        merged = db.get(models.PassageRevision, host.active_revision_id)
        assert merged is not None
        remaining = [
            s for s in merged.segments if s.kind == "token" and s.parent_id is None
        ]
        plan = planning.build_smart_plan(db, merged, None)
        labels = {s.id: (s.reference_label or s.kind) for s in merged.segments}
        print(f"orphans remaining: {len(remaining)}")
        print("plan:", [(item["mode"], labels.get(item["segment_id"], "?")) for item in plan])


if __name__ == "__main__":
    main()
