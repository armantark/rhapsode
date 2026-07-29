from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.orm import Session, selectinload

from rhapsode import models, schemas
from rhapsode.services import furigana


class PracticedRevisionError(ValueError):
    pass


# Words of context on each side of a line boundary (grill B3). Three words is
# enough to recognize the landing site without re-drilling the whole line.
JUNCTURE_SPAN = 3


def _tail(text: str) -> str:
    units, joiner = _juncture_units(text)
    return ("… " if len(units) > JUNCTURE_SPAN else "") + joiner.join(
        units[-JUNCTURE_SPAN:]
    )


def _head(text: str) -> str:
    units, joiner = _juncture_units(text)
    return joiner.join(units[:JUNCTURE_SPAN]) + (" …" if len(units) > JUNCTURE_SPAN else "")


def _juncture_units(text: str) -> tuple[list[str], str]:
    if _contains_japanese(text):
        tokens = furigana.token_texts(text)
        if tokens:
            return tokens, ""
    return text.split(), " "


def _contains_japanese(text: str) -> bool:
    return any(
        "\u3040" <= char <= "\u30ff" or "\u3400" <= char <= "\u9fff" for char in text
    )


def add_junctures(
    db: Session, revision_id: str, segments: list[models.Segment]
) -> list[models.Segment]:
    """Generate juncture segments between consecutive lines: cue is the tail
    of line N, target is the head of line N+1. The between-lines transition is
    the classic oral-verse failure point and deserves its own review state.
    Idempotent so it can also backfill already-practiced revisions."""
    lines = sorted(
        (segment for segment in segments if segment.kind == "line"),
        key=lambda segment: segment.ordinal,
    )
    existing = {
        (segment.metadata_json or {}).get("juncture_after")
        for segment in segments
        if segment.kind == "juncture"
    }
    created: list[models.Segment] = []
    for previous, following in zip(lines, lines[1:], strict=False):
        if previous.ordinal in existing:
            continue
        juncture = models.Segment(
            revision_id=revision_id,
            kind="juncture",
            # Same ordinal as the line it leads into; the planner breaks the
            # tie so the transition drills right before its landing line.
            ordinal=following.ordinal,
            text=_head(following.text),
            cue=_tail(previous.text),
            metadata_json={"juncture_after": previous.ordinal},
        )
        db.add(juncture)
        created.append(juncture)
    db.flush()
    return created


def refresh_junctures(
    db: Session, revision: models.PassageRevision
) -> dict[str, int]:
    lines = sorted(
        (segment for segment in revision.segments if segment.kind == "line"),
        key=lambda segment: segment.ordinal,
    )
    line_by_previous = {
        previous.ordinal: (previous, following)
        for previous, following in zip(lines, lines[1:], strict=False)
    }
    updated = 0
    for juncture in (segment for segment in revision.segments if segment.kind == "juncture"):
        previous_ordinal = (juncture.metadata_json or {}).get("juncture_after")
        if not isinstance(previous_ordinal, int):
            continue
        pair = line_by_previous.get(previous_ordinal)
        if pair is None:
            continue
        previous, following = pair
        text = _head(following.text)
        cue = _tail(previous.text)
        if juncture.text != text or juncture.cue != cue:
            juncture.text = text
            juncture.cue = cue
            updated += 1
    if updated:
        db.flush()
    return {"updated": updated}


def add_segments(
    db: Session, revision: models.PassageRevision, inputs: list[schemas.SegmentInput]
) -> list[models.Segment]:
    client_map: dict[str, str] = {}
    created: list[models.Segment] = []
    # Junctures are always derived, never authored: dropping inbound ones
    # keeps revision forks from duplicating them.
    inputs = [item for item in inputs if item.kind != "juncture"]
    for item in sorted(inputs, key=lambda value: value.ordinal):
        parent_id = client_map.get(item.parent_client_id or "")
        segment = models.Segment(
            revision_id=revision.id,
            parent_id=parent_id,
            kind=item.kind,
            ordinal=item.ordinal,
            text=item.text,
            reference_label=item.reference_label,
            cue=item.cue,
            metadata_json=item.metadata_json,
        )
        db.add(segment)
        db.flush()
        if item.client_id:
            client_map[item.client_id] = segment.id
        for annotation in item.annotations:
            db.add(
                models.Annotation(
                    segment_id=segment.id,
                    layer=annotation.layer,
                    value=annotation.value,
                    data=annotation.data,
                )
            )
        created.append(segment)
    created.extend(add_junctures(db, revision.id, created))
    furigana.apply_local_readings(db, revision)
    return created


def create_revision(
    db: Session, passage: models.Passage, payload: schemas.RevisionInput
) -> models.PassageRevision:
    number = db.scalar(
        select(func.coalesce(func.max(models.PassageRevision.revision_number), 0)).where(
            models.PassageRevision.passage_id == passage.id
        )
    )
    revision = models.PassageRevision(
        passage_id=passage.id,
        revision_number=int(number or 0) + 1,
        source_text=payload.source_text,
        reference_label=payload.reference_label,
        hierarchy=payload.hierarchy,
    )
    db.add(revision)
    db.flush()
    add_segments(db, revision, payload.segments)
    passage.active_revision_id = revision.id
    db.commit()
    return get_revision(db, revision.id)


def replace_segments(
    db: Session, revision: models.PassageRevision, inputs: list[schemas.SegmentInput]
) -> models.PassageRevision:
    if revision.practiced:
        raise PracticedRevisionError("Practiced revisions are immutable; create a new revision.")
    for segment in list(revision.segments):
        db.delete(segment)
    db.flush()
    add_segments(db, revision, inputs)
    db.commit()
    return get_revision(db, revision.id)


APPENDABLE_KINDS = ("line", "chunk")


def append_segments(
    db: Session, revision: models.PassageRevision, inputs: list[schemas.SegmentInput]
) -> models.PassageRevision:
    """Add new lines to the END of a revision WITHOUT touching what's there.

    Unlike replace_segments this is allowed on practiced revisions: the
    immutability rule protects recall targets from changing under existing
    review history, and an append changes nothing that already exists — the
    prior lines keep their exact text, ordinals, and review states, while the
    new lines start fresh. This is the frictionless path for incremental
    growth (a class assigns more lines each week) instead of forking a whole
    revision and orphaning progress on the lines already learned."""
    top_level_ordinals = [
        segment.ordinal
        for segment in revision.segments
        if segment.kind in APPENDABLE_KINDS
    ]
    offset = (max(top_level_ordinals) + 1) if top_level_ordinals else 0
    # Only top-level lines/chunks shift after the existing material; token
    # children keep their parent-relative ordinal, and derived junctures are
    # dropped (add_junctures rebuilds the boundary below).
    shifted = [
        item.model_copy(update={"ordinal": item.ordinal + offset})
        if item.parent_client_id is None
        else item
        for item in inputs
        if item.kind != "juncture"
    ]
    add_segments(db, revision, shifted)
    db.flush()
    # add_segments only saw the new segments, so the juncture bridging the
    # last prior line into the first appended line was not created; refreshing
    # over the full revision creates it (add_junctures is idempotent) and
    # re-running the local readings covers that new juncture for Japanese.
    all_segments = list(
        db.scalars(select(models.Segment).where(models.Segment.revision_id == revision.id))
    )
    add_junctures(db, revision.id, all_segments)
    furigana.apply_local_readings(db, revision)
    new_lines = [
        item.text
        for item in inputs
        if item.kind == "line" and item.parent_client_id is None
    ]
    if new_lines:
        parts = [revision.source_text, *new_lines] if revision.source_text else new_lines
        revision.source_text = "\n".join(parts)
    db.commit()
    # Reading revision.segments above loaded the collection into the identity
    # map; the appended rows were attached by foreign key, not through the
    # relationship, so the cached collection is stale. Expire it so the
    # returning query reloads the full, current set.
    db.expire_all()
    return get_revision(db, revision.id)


def merge_passages(
    db: Session,
    host: models.Passage,
    sources: list[models.Passage],
) -> dict[str, int]:
    """Stitch source passages onto the END of the host passage, in order,
    carrying every learning artifact along.

    A work that grows in batches (the Iliad, assigned a few lines each week)
    belongs in ONE passage: the runway then spans the whole text, junctures
    generate at every line boundary including the former passage seams, and
    collections go back to being shelves for families of works. This performs
    the one-time repair for material that accumulated as separate passages.

    The host keeps its segment ids untouched; each source's lines are appended
    through the same path incremental additions use (append_segments), then
    the source's review states, attempts, review logs, notes, and media are
    re-pointed at the new segment rows. Seam junctures start fresh — they gate
    on their flanks' mastery like any other juncture. Source passages are kept
    (their completed session history still references them) but marked merged,
    and their collection memberships transfer to the host. append_segments
    commits per source, so a mid-merge failure needs the backup the CLI script
    takes first."""
    merged_marker = "Merged into"
    moved = {"lines": 0, "junctures": 0, "states": 0, "attempts": 0, "media": 0}
    for source in sources:
        if source.id == host.id:
            raise ValueError("A passage cannot be merged into itself.")
        if source.language_profile_id != host.language_profile_id:
            raise ValueError(f"{source.title}: language profile differs from the host.")
        if source.description and merged_marker in source.description:
            raise ValueError(f"{source.title}: already merged.")
    host_revision = get_revision(db, host.active_revision_id or "")
    host_kinds = {segment.kind for segment in host_revision.segments}
    for source in sources:
        source_revision = get_revision(db, source.active_revision_id or "")
        source_lines = sorted(
            (s for s in source_revision.segments if s.kind in APPENDABLE_KINDS),
            key=lambda segment: segment.ordinal,
        )
        if {s.kind for s in source_lines} - host_kinds:
            raise ValueError(f"{source.title}: segment grain differs from the host.")
        children_by_parent: dict[str, list[models.Segment]] = {}
        for segment in source_revision.segments:
            if segment.parent_id is not None:
                children_by_parent.setdefault(segment.parent_id, []).append(segment)

        def _input(segment: models.Segment, parent: models.Segment | None) -> schemas.SegmentInput:
            return schemas.SegmentInput(
                client_id=segment.id,
                parent_client_id=parent.id if parent is not None else None,
                kind=segment.kind,
                ordinal=segment.ordinal,
                text=segment.text,
                reference_label=segment.reference_label,
                cue=segment.cue,
                metadata_json=segment.metadata_json or {},
                annotations=[
                    schemas.AnnotationInput(
                        layer=annotation.layer,
                        value=annotation.value,
                        data=annotation.data,
                    )
                    for annotation in segment.annotations
                ],
            )

        prior_ids = {
            segment.id
            for segment in host_revision.segments
            if segment.kind in APPENDABLE_KINDS
        }
        prior_max = max(
            (
                segment.ordinal
                for segment in host_revision.segments
                if segment.kind in APPENDABLE_KINDS
            ),
            default=-1,
        )
        offset = prior_max + 1
        inputs: list[schemas.SegmentInput] = []
        for line in source_lines:
            inputs.append(_input(line, None))
            for child in sorted(
                children_by_parent.get(line.id, []), key=lambda s: s.ordinal
            ):
                # add_segments processes inputs sorted by ordinal and resolves
                # parent_client_id against already-created rows. append shifts
                # only top-level ordinals, so an unshifted child would sort
                # BEFORE its shifted parent and be orphaned to the top level
                # (the merged-Iliad word-soup bug). Shift children by the same
                # offset their parents will receive.
                inputs.append(
                    _input(child, line).model_copy(
                        update={"ordinal": child.ordinal + offset}
                    )
                )
        host_revision = append_segments(db, host_revision, inputs)

        appended = sorted(
            (
                segment
                for segment in host_revision.segments
                if segment.kind in APPENDABLE_KINDS and segment.id not in prior_ids
            ),
            key=lambda segment: segment.ordinal,
        )
        if len(appended) != len(source_lines):
            raise RuntimeError(f"{source.title}: appended line count mismatch.")
        id_map = {
            old.id: new.id for old, new in zip(source_lines, appended, strict=True)
        }
        moved["lines"] += len(source_lines)
        new_junctures_by_after = {
            (segment.metadata_json or {}).get("juncture_after"): segment
            for segment in host_revision.segments
            if segment.kind == "juncture"
        }
        for juncture in (
            s for s in source_revision.segments if s.kind == "juncture"
        ):
            after = (juncture.metadata_json or {}).get("juncture_after")
            if not isinstance(after, int):
                continue
            counterpart = new_junctures_by_after.get(after + offset)
            if counterpart is not None:
                id_map[juncture.id] = counterpart.id
                moved["junctures"] += 1

        for old_id, new_id in id_map.items():
            states_result = db.execute(
                update(models.ReviewState)
                .where(models.ReviewState.segment_id == old_id)
                .values(segment_id=new_id)
            )
            moved["states"] += cast(CursorResult[Any], states_result).rowcount
            attempts_result = db.execute(
                update(models.Attempt)
                .where(models.Attempt.segment_id == old_id)
                .values(segment_id=new_id)
            )
            moved["attempts"] += cast(CursorResult[Any], attempts_result).rowcount
            db.execute(
                update(models.FsrsReviewLog)
                .where(models.FsrsReviewLog.segment_id == old_id)
                .values(segment_id=new_id)
            )
            db.execute(
                update(models.PersonalNote)
                .where(models.PersonalNote.segment_id == old_id)
                .values(segment_id=new_id)
            )
        for asset in db.scalars(
            select(models.MediaAsset).where(
                models.MediaAsset.revision_id == source_revision.id
            )
        ):
            asset.revision_id = host_revision.id
            if asset.segment_id in id_map:
                asset.segment_id = id_map[asset.segment_id]
            if asset.cue_points:
                asset.cue_points = [
                    {
                        **cue,
                        "segment_id": id_map.get(
                            str(cue.get("segment_id")), cue.get("segment_id")
                        ),
                    }
                    for cue in asset.cue_points
                ]
            moved["media"] += 1

        source.description = (
            f"{source.description}\n" if source.description else ""
        ) + f"{merged_marker} {host.title} ({host.id})."
        db.commit()

    # Collection shelves keep one entry for the merged work: the host takes
    # the earliest slot any participant held, and the sources leave.
    member_rows = list(
        db.scalars(
            select(models.CollectionPassage).where(
                models.CollectionPassage.passage_id.in_(
                    [host.id, *[source.id for source in sources]]
                )
            )
        )
    )
    by_collection: dict[str, list[models.CollectionPassage]] = {}
    for row in member_rows:
        by_collection.setdefault(row.collection_id, []).append(row)
    for collection_id, rows in by_collection.items():
        keep_position = min(row.position for row in rows)
        for row in rows:
            db.delete(row)
        db.flush()
        db.add(
            models.CollectionPassage(
                collection_id=collection_id, passage_id=host.id, position=keep_position
            )
        )
    db.commit()
    return moved


def get_revision(db: Session, revision_id: str) -> models.PassageRevision:
    revision = db.scalar(
        select(models.PassageRevision)
        .where(models.PassageRevision.id == revision_id)
        .options(
            selectinload(models.PassageRevision.segments).selectinload(models.Segment.annotations)
        )
    )
    if revision is None:
        raise LookupError("Revision not found")
    return revision
