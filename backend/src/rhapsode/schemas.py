from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Direction(StrEnum):
    ltr = "ltr"
    rtl = "rtl"
    vertical = "vertical"


class AnnotationInput(BaseModel):
    layer: str
    value: str
    data: dict[str, Any] = Field(default_factory=dict)


class AnnotationRead(ORMModel):
    id: str
    segment_id: str
    layer: str
    value: str
    data: dict[str, Any]


class SegmentInput(BaseModel):
    client_id: str | None = None
    parent_client_id: str | None = None
    kind: str
    ordinal: int
    text: str
    cue: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    annotations: list[AnnotationInput] = Field(default_factory=list)


class SegmentRead(ORMModel):
    id: str
    revision_id: str
    parent_id: str | None
    kind: str
    ordinal: int
    text: str
    cue: str | None
    metadata_json: dict[str, Any]
    annotations: list[AnnotationRead] = Field(default_factory=list)


class LanguageProfileInput(BaseModel):
    slug: str
    name: str
    direction: Direction = Direction.ltr
    fonts: list[str] = Field(default_factory=list)
    annotation_schemas: list[dict[str, Any]] = Field(default_factory=list)
    segmentation_defaults: dict[str, Any] = Field(default_factory=dict)
    display_options: dict[str, Any] = Field(default_factory=dict)


class LanguageProfileRead(ORMModel):
    id: str
    slug: str
    name: str
    direction: str
    fonts: list[str]
    annotation_schemas: list[dict[str, Any]]
    segmentation_defaults: dict[str, Any]
    display_options: dict[str, Any]


class PassageInput(BaseModel):
    title: str
    language_profile_id: str
    description: str | None = None
    source_text: str
    hierarchy: dict[str, Any] = Field(default_factory=dict)
    segments: list[SegmentInput] = Field(default_factory=list)


class RevisionInput(BaseModel):
    source_text: str
    hierarchy: dict[str, Any] = Field(default_factory=dict)
    segments: list[SegmentInput] = Field(default_factory=list)


class RevisionRead(ORMModel):
    id: str
    passage_id: str
    revision_number: int
    source_text: str
    hierarchy: dict[str, Any]
    practiced: bool
    segments: list[SegmentRead] = Field(default_factory=list)


class PassageRead(ORMModel):
    id: str
    title: str
    language_profile_id: str
    description: str | None
    active_revision_id: str | None


class PassageDetail(PassageRead):
    active_revision: RevisionRead | None = None


class SegmentsReplaceInput(BaseModel):
    segments: list[SegmentInput]


class AnnotationCreate(AnnotationInput):
    segment_id: str


class CuePoint(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    time: float = Field(ge=0, allow_inf_nan=False)


class CuePointsUpdate(BaseModel):
    cue_points: list[CuePoint] = Field(default_factory=list, max_length=500)


class MediaRead(ORMModel):
    id: str
    revision_id: str | None
    segment_id: str | None
    category: str
    mime_type: str
    original_name: str
    size_bytes: int
    cue_points: list[CuePoint] = Field(default_factory=list)
    created_at: datetime


class PracticeMode(StrEnum):
    shadowing = "shadowing"
    progressive_fading = "progressive_fading"
    forward_chaining = "forward_chaining"
    backward_chaining = "backward_chaining"
    cue_recall = "cue_recall"
    random_start = "random_start"
    weak_link = "weak_link"
    full_passage = "full_passage"


class SessionCreate(BaseModel):
    revision_id: str
    # None means "smart": the planner picks a mode per segment from its
    # mastery stage instead of the caller prescribing a technique.
    modes: list[PracticeMode] | None = None
    segment_kinds: list[str] = Field(default_factory=lambda: ["chunk", "line"])
    # Restrict the plan to segments whose review state is currently due,
    # closing the loop between the review tab and the practice launcher.
    due_only: bool = False


class PracticeItemRead(ORMModel):
    id: str
    session_id: str
    segment_id: str | None
    position: int
    mode: str
    prompt: dict[str, Any]
    completed: bool


class SessionRead(ORMModel):
    id: str
    revision_id: str
    status: str
    plan: dict[str, Any]
    current_index: int
    completed_at: datetime | None
    items: list[PracticeItemRead] = Field(default_factory=list)


class AttemptRating(StrEnum):
    clean = "clean"
    hesitant = "hesitant"
    incorrect = "incorrect"
    revealed = "revealed"


class AttemptCreate(BaseModel):
    item_id: str
    rating: AttemptRating
    latency_ms: int | None = Field(default=None, ge=0)
    media_asset_id: str | None = None


class AttemptRead(ORMModel):
    id: str
    session_id: str
    item_id: str
    segment_id: str | None
    media_asset_id: str | None
    mode: str
    rating: str
    latency_ms: int | None
    revealed: bool
    created_at: datetime


class AttemptResult(BaseModel):
    attempt: AttemptRead
    session: SessionRead
    due_at: datetime | None = None
    mastery_stage: str | None = None


class ReviewStateRead(ORMModel):
    segment_id: str
    due_at: datetime
    mastery_stage: str
    clean_count: int
    attempt_count: int


class MasteryPage(BaseModel):
    items: list[ReviewStateRead]
    total: int
    limit: int
    offset: int


class WeakLinkRead(BaseModel):
    segment_id: str
    text: str
    attempts: int
    difficult_attempts: int
    difficulty_rate: float
    # Hesitation latency is an involuntary difficulty signal the user cannot
    # game by optimistic self-grading.
    mean_latency_ms: int | None = None


class PluginInput(BaseModel):
    plugin_id: str
    kind: str
    name: str
    version: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class PluginRead(ORMModel):
    id: str
    plugin_id: str
    kind: str
    name: str
    version: str
    enabled: bool
    config: dict[str, Any]


class SettingInput(BaseModel):
    value: Any


class SettingRead(BaseModel):
    key: str
    value: Any


class HealthRead(BaseModel):
    status: str
    version: str
