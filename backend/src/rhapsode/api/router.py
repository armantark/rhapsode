from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from rhapsode import __version__, models, schemas
from rhapsode.api.deps import get_session
from rhapsode.config import get_settings
from rhapsode.services import media as media_service
from rhapsode.services import passages as passage_service
from rhapsode.services import planning, prep, scheduling

router = APIRouter(prefix="/api/v1")
Db = Annotated[Session, Depends(get_session)]


def not_found(name: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{name} not found.")


@router.get("/health", response_model=schemas.HealthRead, tags=["system"])
def health() -> schemas.HealthRead:
    return schemas.HealthRead(status="ok", version=__version__)


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
    try:
        revision = passage_service.get_revision(db, payload.revision_id)
    except LookupError as error:
        raise not_found("Revision") from error
    only_segment_ids = None
    if payload.due_only:
        only_segment_ids = planning.due_segment_ids(
            db, [segment.id for segment in revision.segments]
        )
        if not only_segment_ids:
            raise HTTPException(status_code=422, detail="No segments are due for review.")
    if payload.modes is None:
        requested_modes: list[str] = []
        plan = planning.build_smart_plan(
            db,
            revision,
            payload.segment_kinds,
            only_segment_ids,
            minutes=payload.minutes,
        )
    else:
        requested_modes = [mode.value for mode in payload.modes]
        plan = planning.build_plan(
            db, revision, requested_modes, payload.segment_kinds, only_segment_ids
        )
    if not plan:
        raise HTTPException(status_code=422, detail="Revision has no practiceable segments.")
    session = models.PracticeSession(
        revision_id=revision.id,
        plan={
            "modes": requested_modes,
            "segment_kinds": payload.segment_kinds,
            "smart": payload.modes is None,
            "due_only": payload.due_only,
            "minutes": payload.minutes,
        },
    )
    db.add(session)
    db.flush()
    for position, definition in enumerate(plan):
        db.add(models.PracticeItem(session_id=session.id, position=position, **definition))
    revision.practiced = True
    db.commit()
    return get_session_detail(session.id, db)


@router.get("/sessions/{session_id}", response_model=schemas.SessionRead, tags=["practice"])
def get_session_detail(session_id: str, db: Db) -> models.PracticeSession:
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
    query = select(models.PracticeSession).options(selectinload(models.PracticeSession.items))
    if status:
        query = query.where(models.PracticeSession.status == status)
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
    if item.mode == schemas.PracticeMode.full_passage.value:
        affected_ids = list(
            db.scalars(
                select(models.Segment.id)
                .where(models.Segment.revision_id == session.revision_id)
                .order_by(models.Segment.ordinal)
            )
        )
    elif item.segment_id:
        affected_ids = [item.segment_id]
    else:
        affected_ids = []
    snapshot = [scheduling.snapshot_review_state(db, sid) for sid in affected_ids]
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
    item.completed = True
    session.current_index = max(session.current_index, item.position + 1)
    state = None
    for segment_id in affected_ids:
        reviewed = scheduling.review_segment(db, segment_id, payload.rating.value)
        state = state or reviewed
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
    session = db.get(models.PracticeSession, session_id)
    if session is None:
        raise not_found("Session")
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
    return list(
        db.scalars(
            select(models.ReviewState)
            .where(models.ReviewState.due_at <= cutoff)
            .order_by(models.ReviewState.due_at)
        )
    )


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
