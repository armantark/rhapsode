from sqlalchemy import func, select
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
