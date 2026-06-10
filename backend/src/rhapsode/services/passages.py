from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from rhapsode import models, schemas


class PracticedRevisionError(ValueError):
    pass


def add_segments(
    db: Session, revision: models.PassageRevision, inputs: list[schemas.SegmentInput]
) -> list[models.Segment]:
    client_map: dict[str, str] = {}
    created: list[models.Segment] = []
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
