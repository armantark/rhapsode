import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from rhapsode import __version__, models, schemas
from rhapsode.api.deps import get_session
from rhapsode.config import get_settings
from rhapsode.services import backup as backup_service
from rhapsode.services import collections as collection_service
from rhapsode.services import media as media_service
from rhapsode.services import notes as note_service
from rhapsode.services import passages as passage_service
from rhapsode.services import planning, prep, scheduling
from rhapsode.services import sessions as session_service

router = APIRouter(prefix="/api/v1")
Db = Annotated[Session, Depends(get_session)]


def not_found(name: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{name} not found.")


def _library_revisions(db: Session) -> list[models.PassageRevision]:
    """Every passage's active revision, in stable creation order — the corpus
    the library-wide Today queue and its banner both draw from."""
    revisions: list[models.PassageRevision] = []
    for passage in db.scalars(
        select(models.Passage)
        .where(models.Passage.active_revision_id.is_not(None))
        .order_by(models.Passage.created_at)
    ):
        if passage.active_revision_id:
            revisions.append(passage_service.get_revision(db, passage.active_revision_id))
    return revisions


@router.get("/health", response_model=schemas.HealthRead, tags=["system"])
def health() -> schemas.HealthRead:
    return schemas.HealthRead(status="ok", version=__version__)


@router.get("/system/status", response_model=schemas.SystemStatusRead, tags=["system"])
def system_status(db: Db) -> schemas.SystemStatusRead:
    settings = get_settings()
    database_path = settings.database_path()
    last_backup_at = (
        backup_service.newest_snapshot_at(database_path, settings.backup_dir)
        if database_path is not None
        else None
    )
    return schemas.SystemStatusRead(
        backup_dir=str(settings.backup_dir),
        last_backup_at=last_backup_at,
        gemini_key_configured=prep.resolve_api_key(db) is not None,
        fsrs_personal_parameters=scheduling._fsrs_parameters(db) is not None,
        desired_retention=settings.desired_retention,
    )


@router.get("/languages", response_model=list[schemas.LanguageProfileRead], tags=["languages"])
def list_languages(db: Db) -> list[models.LanguageProfile]:
    return list(db.scalars(select(models.LanguageProfile).order_by(models.LanguageProfile.name)))


@router.post(
    "/languages", response_model=schemas.LanguageProfileRead, status_code=201, tags=["languages"]
)
def create_language(payload: schemas.LanguageProfileInput, db: Db) -> models.LanguageProfile:
    if db.scalar(select(models.LanguageProfile).where(models.LanguageProfile.slug == payload.slug)):
        raise HTTPException(status_code=409, detail="Language slug already exists.")
    language = models.LanguageProfile(**payload.model_dump(mode="json"))
    db.add(language)
    db.commit()
    return language


@router.get("/plugins", response_model=list[schemas.PluginRead], tags=["plugins"])
def list_plugins(db: Db) -> list[models.PluginManifest]:
    return list(db.scalars(select(models.PluginManifest).order_by(models.PluginManifest.plugin_id)))


@router.post("/plugins", response_model=schemas.PluginRead, status_code=201, tags=["plugins"])
def register_plugin(payload: schemas.PluginInput, db: Db) -> models.PluginManifest:
    if payload.kind not in {"language", "practice_mode", "speech_scoring"}:
        raise HTTPException(status_code=422, detail="Unsupported plugin kind.")
    if db.scalar(
        select(models.PluginManifest).where(models.PluginManifest.plugin_id == payload.plugin_id)
    ):
        raise HTTPException(status_code=409, detail="Plugin id already exists.")
    plugin = models.PluginManifest(**payload.model_dump())
    db.add(plugin)
    db.commit()
    return plugin


@router.get("/passages", response_model=list[schemas.PassageRead], tags=["passages"])
def list_passages(db: Db) -> list[models.Passage]:
    return list(db.scalars(select(models.Passage).order_by(models.Passage.updated_at.desc())))


@router.post("/passages", response_model=schemas.PassageDetail, status_code=201, tags=["passages"])
def create_passage(payload: schemas.PassageInput, db: Db) -> schemas.PassageDetail:
    if db.get(models.LanguageProfile, payload.language_profile_id) is None:
        raise not_found("Language profile")
    passage = models.Passage(
        title=payload.title,
        language_profile_id=payload.language_profile_id,
        description=payload.description,
    )
    db.add(passage)
    db.flush()
    revision = passage_service.create_revision(
        db,
        passage,
        schemas.RevisionInput(
            source_text=payload.source_text,
            hierarchy=payload.hierarchy,
            segments=payload.segments,
        ),
    )
    return schemas.PassageDetail(
        **schemas.PassageRead.model_validate(passage).model_dump(),
        active_revision=schemas.RevisionRead.model_validate(revision),
    )


@router.delete("/passages/{passage_id}", tags=["passages"])
def delete_passage(passage_id: str, db: Db) -> dict[str, bool]:
    """Remove a passage and everything it owns. The DB cascades handle rows
    (revisions → segments → annotations/review states/notes; its sessions and
    attempts go too), but media files live on disk and would orphan — unlink
    them first. Deliberately destructive; the UI names what dies."""
    passage = db.get(models.Passage, passage_id)
    if passage is None:
        raise not_found("Passage")
    revision_ids = list(
        db.scalars(
            select(models.PassageRevision.id).where(
                models.PassageRevision.passage_id == passage_id
            )
        )
    )
    if revision_ids:
        for asset in db.scalars(
            select(models.MediaAsset).where(models.MediaAsset.revision_id.in_(revision_ids))
        ):
            media_service.remove_asset(asset.storage_path)
    db.delete(passage)
    db.commit()
    return {"deleted": True}


@router.get("/passages/{passage_id}", response_model=schemas.PassageDetail, tags=["passages"])
def get_passage(passage_id: str, db: Db) -> schemas.PassageDetail:
    passage = db.get(models.Passage, passage_id)
    if passage is None:
        raise not_found("Passage")
    revision = (
        passage_service.get_revision(db, passage.active_revision_id)
        if passage.active_revision_id
        else None
    )
    return schemas.PassageDetail(
        **schemas.PassageRead.model_validate(passage).model_dump(),
        active_revision=schemas.RevisionRead.model_validate(revision) if revision else None,
    )


@router.get("/collections", response_model=list[schemas.CollectionRead], tags=["collections"])
def list_collections(db: Db) -> list[schemas.CollectionRead]:
    collections = db.scalars(select(models.Collection).order_by(models.Collection.created_at))
    return [
        collection_service.collection_read(db, collection_service.get_collection(db, item.id))
        for item in collections
    ]


@router.post(
    "/collections", response_model=schemas.CollectionRead, status_code=201, tags=["collections"]
)
def create_collection(payload: schemas.CollectionCreate, db: Db) -> schemas.CollectionRead:
    collection = models.Collection(name=payload.name)
    db.add(collection)
    db.commit()
    return collection_service.collection_read(
        db, collection_service.get_collection(db, collection.id)
    )


@router.get(
    "/collections/{collection_id}", response_model=schemas.CollectionRead, tags=["collections"]
)
def get_collection(collection_id: str, db: Db) -> schemas.CollectionRead:
    try:
        collection = collection_service.get_collection(db, collection_id)
    except LookupError as error:
        raise not_found("Collection") from error
    return collection_service.collection_read(db, collection)


@router.put(
    "/collections/{collection_id}", response_model=schemas.CollectionRead, tags=["collections"]
)
def update_collection(
    collection_id: str, payload: schemas.CollectionCreate, db: Db
) -> schemas.CollectionRead:
    try:
        collection = collection_service.get_collection(db, collection_id)
    except LookupError as error:
        raise not_found("Collection") from error
    collection.name = payload.name
    db.commit()
    return collection_service.collection_read(db, collection)


@router.delete("/collections/{collection_id}", tags=["collections"])
def delete_collection(collection_id: str, db: Db) -> dict[str, bool]:
    try:
        collection = collection_service.get_collection(db, collection_id)
    except LookupError as error:
        raise not_found("Collection") from error
    db.delete(collection)
    db.commit()
    return {"deleted": True}


@router.post(
    "/collections/{collection_id}/members",
    response_model=schemas.CollectionRead,
    tags=["collections"],
)
def add_collection_member(
    collection_id: str, payload: schemas.CollectionMemberAdd, db: Db
) -> schemas.CollectionRead:
    try:
        collection = collection_service.get_collection(db, collection_id)
    except LookupError as error:
        raise not_found("Collection") from error
    if db.get(models.Passage, payload.passage_id) is None:
        raise not_found("Passage")
    if any(member.passage_id == payload.passage_id for member in collection.members):
        raise HTTPException(status_code=409, detail="Passage is already in this collection.")
    collection.members.append(
        models.CollectionPassage(passage_id=payload.passage_id, position=len(collection.members))
    )
    db.commit()
    return collection_service.collection_read(
        db, collection_service.get_collection(db, collection_id)
    )


@router.delete(
    "/collections/{collection_id}/members/{passage_id}",
    response_model=schemas.CollectionRead,
    tags=["collections"],
)
def remove_collection_member(
    collection_id: str, passage_id: str, db: Db
) -> schemas.CollectionRead:
    try:
        collection = collection_service.get_collection(db, collection_id)
    except LookupError as error:
        raise not_found("Collection") from error
    member = next(
        (member for member in collection.members if member.passage_id == passage_id), None
    )
    if member is None:
        raise not_found("Collection member")
    db.delete(member)
    db.flush()
    remaining = [item for item in collection.members if item is not member]
    for position, item in enumerate(remaining):
        item.position = position
    db.commit()
    return collection_service.collection_read(
        db, collection_service.get_collection(db, collection_id)
    )


@router.put(
    "/collections/{collection_id}/members",
    response_model=schemas.CollectionRead,
    tags=["collections"],
)
def reorder_collection_members(
    collection_id: str, payload: schemas.CollectionMembersReorder, db: Db
) -> schemas.CollectionRead:
    try:
        collection = collection_service.get_collection(db, collection_id)
    except LookupError as error:
        raise not_found("Collection") from error
    current_ids = {member.passage_id for member in collection.members}
    requested_ids = set(payload.passage_ids)
    if len(requested_ids) != len(payload.passage_ids) or requested_ids != current_ids:
        raise HTTPException(
            status_code=422,
            detail="Reorder must contain every collection passage exactly once.",
        )
    by_passage = {member.passage_id: member for member in collection.members}
    # Shift away from the unique position range before assigning the final
    # order, so SQLite never observes a transient duplicate position.
    for member in collection.members:
        member.position += len(collection.members)
    db.flush()
    for position, passage_id in enumerate(payload.passage_ids):
        by_passage[passage_id].position = position
    db.commit()
    return collection_service.collection_read(
        db, collection_service.get_collection(db, collection_id)
    )


@router.post(
    "/passages/{passage_id}/revisions",
    response_model=schemas.RevisionRead,
    status_code=201,
    tags=["passages"],
)
def create_revision(
    passage_id: str, payload: schemas.RevisionInput, db: Db
) -> models.PassageRevision:
    passage = db.get(models.Passage, passage_id)
    if passage is None:
        raise not_found("Passage")
    return passage_service.create_revision(db, passage, payload)


@router.get("/revisions/{revision_id}", response_model=schemas.RevisionRead, tags=["passages"])
def get_revision(revision_id: str, db: Db) -> models.PassageRevision:
    try:
        return passage_service.get_revision(db, revision_id)
    except LookupError as error:
        raise not_found("Revision") from error


@router.put(
    "/revisions/{revision_id}/segments", response_model=schemas.RevisionRead, tags=["passages"]
)
def replace_segments(
    revision_id: str, payload: schemas.SegmentsReplaceInput, db: Db
) -> models.PassageRevision:
    try:
        revision = passage_service.get_revision(db, revision_id)
        return passage_service.replace_segments(db, revision, payload.segments)
    except LookupError as error:
        raise not_found("Revision") from error
    except passage_service.PracticedRevisionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post(
    "/revisions/{revision_id}/segments", response_model=schemas.RevisionRead, tags=["passages"]
)
def append_segments(
    revision_id: str, payload: schemas.SegmentsReplaceInput, db: Db
) -> models.PassageRevision:
    """Append lines in place. Allowed on practiced revisions (unlike the PUT
    replace) because it never changes existing recall targets or their review
    history — the frictionless path for growing a passage incrementally."""
    try:
        revision = passage_service.get_revision(db, revision_id)
        return passage_service.append_segments(db, revision, payload.segments)
    except LookupError as error:
        raise not_found("Revision") from error


@router.post(
    "/revisions/{revision_id}/prep-suggestions",
    response_model=schemas.PrepSuggestResult,
    tags=["passages"],
)
def prep_suggestions(
    revision_id: str, payload: schemas.PrepSuggestInput, db: Db
) -> schemas.PrepSuggestResult:
    try:
        revision = passage_service.get_revision(db, revision_id)
    except LookupError as error:
        raise not_found("Revision") from error
    unknown = set(payload.layers) - set(prep.PREP_LAYERS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown prep layers: {sorted(unknown)}")
    try:
        written = prep.suggest_prep(db, revision, payload.layers)
    except prep.PrepUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return schemas.PrepSuggestResult(written=written)


@router.post(
    "/annotations", response_model=schemas.AnnotationRead, status_code=201, tags=["passages"]
)
def create_annotation(payload: schemas.AnnotationCreate, db: Db) -> models.Annotation:
    # Practiced-revision immutability deliberately does NOT apply here: it
    # protects the recall target (the text), while annotations are support
    # layers. Backfilling meter or glosses onto an in-progress passage must
    # not require a new revision that would orphan review states.
    segment = db.get(models.Segment, payload.segment_id)
    if segment is None:
        raise not_found("Segment")
    annotation = models.Annotation(**payload.model_dump())
    db.add(annotation)
    db.commit()
    return annotation


@router.delete("/annotations/{annotation_id}", status_code=200, tags=["passages"])
def delete_annotation(annotation_id: str, db: Db) -> dict[str, bool]:
    annotation = db.get(models.Annotation, annotation_id)
    if annotation is None:
        raise not_found("Annotation")
    db.delete(annotation)
    db.commit()
    return {"deleted": True}


@router.get(
    "/segments/{segment_id}/note",
    response_model=schemas.PersonalNoteRead,
    tags=["passages"],
)
def get_personal_note(segment_id: str, db: Db) -> models.PersonalNote:
    if db.get(models.Segment, segment_id) is None:
        raise not_found("Segment")
    note = note_service.get_note(db, segment_id)
    if note is None:
        raise not_found("Personal note")
    return note


@router.put(
    "/segments/{segment_id}/note",
    response_model=schemas.PersonalNoteRead,
    tags=["passages"],
)
def put_personal_note(
    segment_id: str, payload: schemas.PersonalNotePut, db: Db
) -> models.PersonalNote:
    try:
        return note_service.put_note(db, segment_id, payload.text)
    except LookupError as error:
        raise not_found("Segment") from error


@router.post("/media", response_model=schemas.MediaRead, status_code=201, tags=["media"])
def upload_media(
    db: Db,
    category: Annotated[str, Form()],
    upload: Annotated[UploadFile, File()],
    revision_id: Annotated[str | None, Form()] = None,
    segment_id: Annotated[str | None, Form()] = None,
) -> models.MediaAsset:
    if category not in media_service.ALLOWED_CATEGORIES:
        raise HTTPException(
            status_code=422, detail="Only reference and saved_best audio may persist."
        )
    if not (upload.content_type or "").startswith("audio/"):
        raise HTTPException(status_code=422, detail="Persisted media must be audio.")
    if revision_id and db.get(models.PassageRevision, revision_id) is None:
        raise not_found("Revision")
    if segment_id and db.get(models.Segment, segment_id) is None:
        raise not_found("Segment")
    storage_path, size = media_service.store_upload(upload, get_settings().media_dir)
    asset = models.MediaAsset(
        revision_id=revision_id,
        segment_id=segment_id,
        category=category,
        mime_type=upload.content_type or "application/octet-stream",
        original_name=upload.filename or "recording",
        storage_path=storage_path,
        size_bytes=size,
        cue_points=[],
    )
    db.add(asset)
    db.commit()
    return asset


@router.get("/media", response_model=list[schemas.MediaRead], tags=["media"])
def list_media(
    db: Db, revision_id: str | None = None, category: str | None = None
) -> list[models.MediaAsset]:
    if category is not None and category not in media_service.ALLOWED_CATEGORIES:
        raise HTTPException(status_code=422, detail="Unsupported media category.")
    query = select(models.MediaAsset)
    if revision_id is not None:
        query = query.where(models.MediaAsset.revision_id == revision_id)
    if category is not None:
        query = query.where(models.MediaAsset.category == category)
    return list(
        db.scalars(query.order_by(models.MediaAsset.created_at.desc(), models.MediaAsset.id))
    )


@router.get("/media/{media_id}/content", tags=["media"])
def stream_media(media_id: str, db: Db) -> FileResponse:
    asset = db.get(models.MediaAsset, media_id)
    if asset is None:
        raise not_found("Media")
    if not Path(asset.storage_path).exists():
        raise HTTPException(status_code=410, detail="Media file is missing.")
    return FileResponse(
        asset.storage_path, media_type=asset.mime_type, filename=asset.original_name
    )


@router.put("/media/{media_id}/cues", response_model=schemas.MediaRead, tags=["media"])
def replace_media_cues(
    media_id: str, payload: schemas.CuePointsUpdate, db: Db
) -> models.MediaAsset:
    asset = db.get(models.MediaAsset, media_id)
    if asset is None:
        raise not_found("Media")
    asset.cue_points = [
        cue.model_dump() for cue in sorted(payload.cue_points, key=lambda cue: cue.time)
    ]
    db.commit()
    return asset


@router.delete("/media/{media_id}", tags=["media"])
def delete_media(media_id: str, db: Db) -> dict[str, bool]:
    asset = db.get(models.MediaAsset, media_id)
    if asset is None:
        raise not_found("Media")
    media_service.remove_asset(asset.storage_path)
    db.delete(asset)
    db.commit()
    return {"deleted": True}


@router.post("/sessions", response_model=schemas.SessionRead, status_code=201, tags=["practice"])
def create_session(payload: schemas.SessionCreate, db: Db) -> models.PracticeSession:
    session_service.expire_stale_sessions(db)
    collection = None
    if payload.collection_id is not None:
        try:
            collection = collection_service.get_collection(db, payload.collection_id)
        except LookupError as error:
            raise not_found("Collection") from error
        revisions = collection_service.active_revisions(db, collection)
        if not revisions:
            raise HTTPException(status_code=422, detail="Collection has no active passages.")
    elif payload.revision_id is not None:
        try:
            revisions = [passage_service.get_revision(db, payload.revision_id)]
        except LookupError as error:
            raise not_found("Revision") from error
    else:
        # No target + due_only (schema-enforced): the library-wide Today
        # queue over every passage's active revision.
        revisions = _library_revisions(db)
        if not revisions:
            raise HTTPException(status_code=422, detail="The library has no passages yet.")
    only_segment_ids = None
    if payload.due_only:
        # Only segments the planner can actually serve are candidates for a
        # due-review session. Word tokens may carry stale review states from an
        # earlier full-passage grade, but they are not review units, so a due
        # session built from them would plan nothing and 422.
        practiceable_ids: list[str] = []
        for revision in revisions:
            kinds = planning.practiceable_kinds(revision)
            practiceable_ids.extend(
                segment.id for segment in revision.segments if segment.kind in kinds
            )
        only_segment_ids = planning.due_segment_ids(db, practiceable_ids)
        if not only_segment_ids:
            raise HTTPException(status_code=422, detail="No segments are due for review.")
    library_wide = payload.revision_id is None and payload.collection_id is None
    if payload.modes is None:
        requested_modes: list[str] = []
        plan = planning.build_smart_plan_for_revisions(
            db,
            revisions,
            payload.segment_kinds,
            only_segment_ids,
            minutes=payload.minutes,
            # A due queue must be clearable: the momentum cap is for
            # exploratory smart sessions, and FSRS already bounds the queue.
            cap=None if library_wide else planning.SMART_SESSION_CAP,
        )
    else:
        requested_modes = [mode.value for mode in payload.modes]
        plan = [
            item
            for revision in revisions
            for item in planning.build_plan(
                db, revision, requested_modes, payload.segment_kinds, only_segment_ids
            )
        ]
    if not plan:
        raise HTTPException(status_code=422, detail="Target has no practiceable segments.")
    session = models.PracticeSession(
        # Only a single-passage launch pins the session to one revision; a
        # collection or library-wide session resolves revisions per item.
        revision_id=payload.revision_id,
        collection_id=collection.id if collection is not None else None,
        plan={
            "modes": requested_modes,
            "segment_kinds": payload.segment_kinds,
            "smart": payload.modes is None,
            "due_only": payload.due_only,
            "minutes": payload.minutes,
            "revision_ids": [revision.id for revision in revisions],
        },
    )
    db.add(session)
    db.flush()
    for position, definition in enumerate(plan):
        db.add(models.PracticeItem(session_id=session.id, position=position, **definition))
    for revision in revisions:
        revision.practiced = True
    db.commit()
    return get_session_detail(session.id, db)


@router.get("/sessions/{session_id}", response_model=schemas.SessionRead, tags=["practice"])
def get_session_detail(session_id: str, db: Db) -> models.PracticeSession:
    session_service.expire_stale_sessions(db)
    session = db.scalar(
        select(models.PracticeSession)
        .where(models.PracticeSession.id == session_id)
        .options(selectinload(models.PracticeSession.items))
    )
    if session is None:
        raise not_found("Session")
    return session


@router.get("/sessions", response_model=list[schemas.SessionRead], tags=["practice"])
def list_sessions(db: Db, status: str | None = None) -> list[models.PracticeSession]:
    session_service.expire_stale_sessions(db)
    query = select(models.PracticeSession).options(selectinload(models.PracticeSession.items))
    if status:
        query = query.where(models.PracticeSession.status == status)
    else:
        query = query.where(models.PracticeSession.status != "expired")
    return list(db.scalars(query.order_by(models.PracticeSession.updated_at.desc())))


@router.post(
    "/sessions/{session_id}/attempts",
    response_model=schemas.AttemptResult,
    status_code=201,
    tags=["practice"],
)
def submit_attempt(
    session_id: str, payload: schemas.AttemptCreate, db: Db
) -> schemas.AttemptResult:
    session_service.expire_stale_sessions(db)
    session = db.get(models.PracticeSession, session_id)
    if session is None:
        raise not_found("Session")
    if session.status != "active":
        raise HTTPException(status_code=409, detail="Session is not active.")
    item = db.get(models.PracticeItem, payload.item_id)
    if item is None or item.session_id != session_id:
        raise not_found("Practice item")
    if item.completed:
        raise HTTPException(status_code=409, detail="Practice item is already completed.")
    if payload.media_asset_id:
        saved_media = db.get(models.MediaAsset, payload.media_asset_id)
        if saved_media is None:
            raise not_found("Media")
        if saved_media.category != "saved_best":
            raise HTTPException(
                status_code=422, detail="Only saved_best media may be attached to an attempt."
            )
    if payload.stumbled_segment_ids is not None and item.mode != schemas.PracticeMode.recital.value:
        raise HTTPException(
            status_code=422, detail="Only recital attempts carry a stumble map."
        )
    # Each affected review unit is (segment_id, rating). Every mode grades all
    # its units with the pressed rating except recital, whose stumble map
    # yields per-line grades from one performance.
    affected: list[tuple[str, str]] = []
    if item.mode == schemas.PracticeMode.recital.value:
        revision_id = item.revision_id or session.revision_id
        revision = db.get(models.PassageRevision, revision_id) if revision_id else None
        if revision is not None:
            kinds = planning.practiceable_kinds(revision)
            units = [
                segment
                for segment in sorted(revision.segments, key=lambda segment: segment.ordinal)
                if segment.kind in kinds
            ]
            stumbled = set(payload.stumbled_segment_ids or [])
            flaggable_ids = {unit.id for unit in units if unit.kind != "juncture"}
            if not stumbled <= flaggable_ids:
                raise HTTPException(
                    status_code=422,
                    detail="Stumbled segments must be lines of the recited passage.",
                )
            # Junctures inherit their landing line's rating: the seam into a
            # stumbled line is where the stumble lives. Stumbles are lapses
            # ("incorrect"); a clean recital pass is solid-but-not-effortless
            # evidence, so unflagged units grade Good ("hesitant").
            landing_by_ordinal = {
                unit.ordinal: unit.id for unit in units if unit.kind != "juncture"
            }
            for unit in units:
                flagged_id = (
                    landing_by_ordinal.get(unit.ordinal)
                    if unit.kind == "juncture"
                    else unit.id
                )
                rating = "incorrect" if flagged_id in stumbled else "hesitant"
                affected.append((unit.id, rating))
    elif item.mode == schemas.PracticeMode.full_passage.value:
        # A full-passage recitation advances every review unit of the passage,
        # but only the review units: fanning the grade onto word tokens would
        # mint review states the planner can never schedule, surfacing them as
        # permanently-"due" yet unpracticeable segments.
        revision_id = item.revision_id or session.revision_id
        revision = db.get(models.PassageRevision, revision_id) if revision_id else None
        if revision is not None:
            kinds = planning.practiceable_kinds(revision)
            affected = [
                (segment.id, payload.rating.value)
                for segment in sorted(revision.segments, key=lambda segment: segment.ordinal)
                if segment.kind in kinds
            ]
    elif item.mode in {
        schemas.PracticeMode.forward_chaining.value,
        schemas.PracticeMode.backward_chaining.value,
    }:
        prompt = item.prompt if isinstance(item.prompt, dict) else {}
        chain_segment_ids = prompt.get("chain_segment_ids")
        affected = (
            [
                (segment_id, payload.rating.value)
                for segment_id in chain_segment_ids
                if isinstance(segment_id, str)
            ]
            if isinstance(chain_segment_ids, list)
            else ([(item.segment_id, payload.rating.value)] if item.segment_id else [])
        )
    elif item.segment_id:
        affected = [(item.segment_id, payload.rating.value)]
    snapshot = [scheduling.snapshot_review_state(db, sid) for sid, _ in affected]
    attempt = models.Attempt(
        session_id=session_id,
        item_id=item.id,
        segment_id=item.segment_id,
        media_asset_id=payload.media_asset_id,
        mode=item.mode,
        rating=payload.rating.value,
        latency_ms=payload.latency_ms,
        revealed=payload.revealed,
        review_snapshot=snapshot,
    )
    db.add(attempt)
    # Flush so the attempt has its id: the review logs written below key to it
    # (undo cascades them away with the attempt).
    db.flush()
    item.completed = True
    session.current_index = max(session.current_index, item.position + 1)
    state = None
    # A card's latency is only meaningful per review when the card touched one
    # segment; fanned grades would teach the optimizer one latency many times.
    log_duration = payload.latency_ms if len(affected) == 1 else None
    for segment_id, rating in affected:
        reviewed = scheduling.review_segment(
            db, segment_id, rating, attempt_id=attempt.id, review_duration_ms=log_duration
        )
        state = state or reviewed
    # The completion check below is SQL; without a flush a session factory
    # configured with autoflush=False would never see this item complete.
    db.flush()
    remaining = db.scalar(
        select(func.count(models.PracticeItem.id)).where(
            models.PracticeItem.session_id == session_id,
            models.PracticeItem.completed.is_(False),
        )
    )
    if remaining == 0:
        session.status = "completed"
        session.completed_at = datetime.now(UTC)
    db.commit()
    return schemas.AttemptResult(
        attempt=schemas.AttemptRead.model_validate(attempt),
        session=schemas.SessionRead.model_validate(get_session_detail(session_id, db)),
        due_at=state.due_at if state else None,
        mastery_stage=state.mastery_stage if state else None,
    )


@router.post(
    "/sessions/{session_id}/undo", response_model=schemas.SessionRead, tags=["practice"]
)
def undo_attempt(session_id: str, db: Db) -> schemas.SessionRead:
    session_service.expire_stale_sessions(db)
    session = db.get(models.PracticeSession, session_id)
    if session is None:
        raise not_found("Session")
    if session.status == "expired":
        raise HTTPException(status_code=409, detail="Expired sessions cannot be reopened.")
    attempt = db.scalar(
        select(models.Attempt)
        .where(models.Attempt.session_id == session_id)
        .order_by(models.Attempt.created_at.desc(), models.Attempt.id.desc())
    )
    if attempt is None:
        raise HTTPException(status_code=409, detail="Nothing to undo in this session.")
    for snapshot in attempt.review_snapshot or []:
        scheduling.restore_review_state(db, snapshot)
    item = db.get(models.PracticeItem, attempt.item_id)
    if item is not None:
        item.completed = False
        session.current_index = item.position
    # Undo can resurrect a session that the final grade had completed.
    session.status = "active"
    session.completed_at = None
    db.delete(attempt)
    db.commit()
    return schemas.SessionRead.model_validate(get_session_detail(session_id, db))


@router.post(
    "/sessions/{session_id}/complete", response_model=schemas.SessionRead, tags=["practice"]
)
def complete_session(session_id: str, db: Db) -> models.PracticeSession:
    session = db.get(models.PracticeSession, session_id)
    if session is None:
        raise not_found("Session")
    session.status = "completed"
    session.completed_at = datetime.now(UTC)
    db.commit()
    return get_session_detail(session_id, db)


@router.get("/analytics/due", response_model=list[schemas.ReviewStateRead], tags=["analytics"])
def due_reviews(db: Db, before: datetime | None = None) -> list[models.ReviewState]:
    cutoff = before or datetime.now(UTC)
    states = list(
        db.scalars(
            select(models.ReviewState)
            .where(models.ReviewState.due_at <= cutoff)
            .order_by(models.ReviewState.due_at)
        )
    )
    if not states:
        return states
    # Hide review states that belong to non-review-unit segments (word tokens
    # left over from an earlier full-passage grade). Listing them would promise
    # a due session the planner cannot build. Grain is per-revision, so the
    # practiceable kinds are resolved once per revision and cached.
    segments = {
        segment.id: segment
        for segment in db.scalars(
            select(models.Segment).where(
                models.Segment.id.in_([state.segment_id for state in states])
            )
        )
    }
    kinds_by_revision: dict[str, list[str]] = {}

    def is_practiceable(segment: models.Segment) -> bool:
        kinds = kinds_by_revision.get(segment.revision_id)
        if kinds is None:
            kinds = planning.practiceable_kinds(segment.revision)
            kinds_by_revision[segment.revision_id] = kinds
        return segment.kind in kinds

    return [
        state
        for state in states
        if (segment := segments.get(state.segment_id)) is not None and is_practiceable(segment)
    ]


@router.get("/analytics/today", response_model=schemas.TodayRead, tags=["analytics"])
def today(db: Db) -> schemas.TodayRead:
    """The daily front door: due queue size and cost, the retention mirror,
    the cross-day streak, and a 7-day workload forecast — everything FSRS
    already knows, surfaced where the day starts."""
    now = datetime.now(UTC)
    revisions = _library_revisions(db)
    practiceable_ids: list[str] = []
    for revision in revisions:
        kinds = planning.practiceable_kinds(revision)
        practiceable_ids.extend(
            segment.id for segment in revision.segments if segment.kind in kinds
        )
    due_ids = planning.due_segment_ids(db, practiceable_ids)
    plan = (
        planning.build_smart_plan_for_revisions(db, revisions, None, due_ids, cap=None)
        if due_ids
        else []
    )
    estimated_minutes = math.ceil(planning.estimate_plan_seconds(db, plan) / 60) if plan else 0

    # Retention mirror: share of logged reviews not rated Again, last 30 days.
    rows = db.execute(
        select(models.FsrsReviewLog.rating, func.count(models.FsrsReviewLog.id))
        .where(models.FsrsReviewLog.reviewed_at >= now - timedelta(days=30))
        .group_by(models.FsrsReviewLog.rating)
    ).all()
    sample = sum(count for _rating, count in rows)
    again = sum(count for rating, count in rows if rating == 1)
    measured = (sample - again) / sample if sample else None

    # Streak: consecutive UTC days with at least one completed session,
    # ending today — or yesterday, so an unpracticed morning shows the streak
    # still alive rather than already broken.
    completed_days = {
        completed_at.date()
        for completed_at in db.scalars(
            select(models.PracticeSession.completed_at).where(
                models.PracticeSession.completed_at.is_not(None)
            )
        )
        if completed_at is not None
    }
    today_date = now.date()
    cursor = today_date if today_date in completed_days else today_date - timedelta(days=1)
    streak = 0
    while cursor in completed_days:
        streak += 1
        cursor -= timedelta(days=1)

    # Forecast: day 0 carries the whole backlog; days 1-6 that day's arrivals.
    due_dates = [
        due_at.date()
        for due_at in db.scalars(
            select(models.ReviewState.due_at).where(
                models.ReviewState.segment_id.in_(practiceable_ids)
            )
        )
    ]
    forecast = []
    for offset in range(7):
        day = today_date + timedelta(days=offset)
        due = (
            sum(1 for due_date in due_dates if due_date <= day)
            if offset == 0
            else sum(1 for due_date in due_dates if due_date == day)
        )
        forecast.append(schemas.TodayForecastDay(date=day, due=due))

    return schemas.TodayRead(
        due_count=len(due_ids),
        estimated_minutes=estimated_minutes,
        desired_retention=get_settings().desired_retention,
        measured_retention=measured,
        retention_sample=sample,
        streak_days=streak,
        forecast=forecast,
    )


@router.get(
    "/analytics/library",
    response_model=list[schemas.LibraryPassageStats],
    tags=["analytics"],
)
def library_stats(db: Db) -> list[schemas.LibraryPassageStats]:
    """Per-passage progress so library cards say where each passage stands
    instead of just naming it."""
    results: list[schemas.LibraryPassageStats] = []
    for revision in _library_revisions(db):
        kinds = planning.practiceable_kinds(revision)
        unit_ids = [
            segment.id for segment in revision.segments if segment.kind in kinds
        ]
        stages = (
            list(
                db.scalars(
                    select(models.ReviewState.mastery_stage).where(
                        models.ReviewState.segment_id.in_(unit_ids)
                    )
                )
            )
            if unit_ids
            else []
        )
        results.append(
            schemas.LibraryPassageStats(
                passage_id=revision.passage_id,
                total_units=len(unit_ids),
                started=bool(stages),
                # SQL-side dueness: SQLite hands back naive datetimes, so the
                # aware/naive comparison stays in the database like elsewhere.
                due=len(planning.due_segment_ids(db, unit_ids)),
                durable=stages.count("durable"),
                review=stages.count("review"),
                learning=stages.count("learning"),
            )
        )
    return results


@router.get("/analytics/mastery", response_model=schemas.MasteryPage, tags=["analytics"])
def mastery(
    db: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> schemas.MasteryPage:
    total = db.scalar(select(func.count(models.ReviewState.id))) or 0
    items = list(
        db.scalars(
            select(models.ReviewState)
            .order_by(models.ReviewState.updated_at.desc(), models.ReviewState.id)
            .limit(limit)
            .offset(offset)
        )
    )
    return schemas.MasteryPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/analytics/weak-links", response_model=list[schemas.WeakLinkRead], tags=["analytics"])
def weak_links(db: Db, revision_id: str | None = None) -> list[schemas.WeakLinkRead]:
    difficult = case((models.Attempt.rating.in_(["incorrect", "revealed"]), 1), else_=0)
    query = (
        select(
            models.Segment.id,
            models.Segment.text,
            func.count(models.Attempt.id),
            func.sum(difficult),
            func.avg(models.Attempt.latency_ms),
        )
        .join(models.Attempt, models.Attempt.segment_id == models.Segment.id)
        .group_by(models.Segment.id)
    )
    if revision_id:
        query = query.where(models.Segment.revision_id == revision_id)
    results = []
    for segment_id, text, attempts, difficult_attempts, mean_latency in db.execute(query):
        difficult_count = int(difficult_attempts or 0)
        results.append(
            schemas.WeakLinkRead(
                segment_id=segment_id,
                text=text,
                attempts=attempts,
                difficult_attempts=difficult_count,
                difficulty_rate=difficult_count / attempts,
                mean_latency_ms=round(mean_latency) if mean_latency is not None else None,
            )
        )
    # Latency breaks ties: between equally error-prone segments, the one the
    # user hesitates longest on is the weaker link.
    return sorted(
        results,
        key=lambda result: (result.difficulty_rate, result.mean_latency_ms or 0),
        reverse=True,
    )


@router.get("/settings", response_model=list[schemas.SettingRead], tags=["settings"])
def list_settings(db: Db) -> list[schemas.SettingRead]:
    return [
        schemas.SettingRead(key=row.key, value=row.value)
        for row in db.scalars(select(models.AppSetting))
    ]


@router.put("/settings/{key}", response_model=schemas.SettingRead, tags=["settings"])
def put_setting(key: str, payload: schemas.SettingInput, db: Db) -> schemas.SettingRead:
    setting = db.get(models.AppSetting, key)
    if setting is None:
        setting = models.AppSetting(key=key, value=payload.value)
        db.add(setting)
    else:
        setting.value = payload.value
    db.commit()
    return schemas.SettingRead(key=setting.key, value=setting.value)
