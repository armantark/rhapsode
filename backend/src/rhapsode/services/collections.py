from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from rhapsode import models, schemas
from rhapsode.services import planning


def get_collection(db: Session, collection_id: str) -> models.Collection:
    collection = db.scalar(
        select(models.Collection)
        .where(models.Collection.id == collection_id)
        .execution_options(populate_existing=True)
        .options(
            selectinload(models.Collection.members).selectinload(
                models.CollectionPassage.passage
            )
        )
    )
    if collection is None:
        raise LookupError("Collection not found")
    return collection


def active_revisions(
    db: Session, collection: models.Collection
) -> list[models.PassageRevision]:
    revision_ids = [
        member.passage.active_revision_id
        for member in collection.members
        if member.passage.active_revision_id is not None
    ]
    if not revision_ids:
        return []
    revisions = {
        revision.id: revision
        for revision in db.scalars(
            select(models.PassageRevision)
            .where(models.PassageRevision.id.in_(revision_ids))
            .options(selectinload(models.PassageRevision.segments))
        )
    }
    return [revisions[revision_id] for revision_id in revision_ids if revision_id in revisions]


def collection_rollup(
    db: Session, revisions: list[models.PassageRevision]
) -> schemas.CollectionRollup:
    segment_ids = [
        segment.id
        for revision in revisions
        for segment in planning._ordered_segments(revision, None)
    ]
    if not segment_ids:
        return schemas.CollectionRollup(due=0, learning=0, new=0)
    states = {
        state.segment_id: state
        for state in db.scalars(
            select(models.ReviewState).where(models.ReviewState.segment_id.in_(segment_ids))
        )
    }
    due_ids = planning.due_segment_ids(db, segment_ids)
    due = learning = new = 0
    for segment_id in segment_ids:
        state = states.get(segment_id)
        if state is None or state.mastery_stage == "new":
            new += 1
        elif state.mastery_stage == "learning":
            learning += 1
        elif segment_id in due_ids:
            due += 1
    return schemas.CollectionRollup(due=due, learning=learning, new=new)


def collection_read(db: Session, collection: models.Collection) -> schemas.CollectionRead:
    return schemas.CollectionRead(
        id=collection.id,
        name=collection.name,
        created_at=collection.created_at,
        members=[
            schemas.CollectionMemberRead.model_validate(member)
            for member in sorted(collection.members, key=lambda member: member.position)
        ],
        rollup=collection_rollup(db, active_revisions(db, collection)),
    )
