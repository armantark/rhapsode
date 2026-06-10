from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rhapsode.database import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LanguageProfile(Base, TimestampMixin):
    __tablename__ = "language_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String, default="ltr")
    fonts: Mapped[list[str]] = mapped_column(JSON, default=list)
    annotation_schemas: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    segmentation_defaults: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    display_options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Passage(Base, TimestampMixin):
    __tablename__ = "passages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String)
    language_profile_id: Mapped[str] = mapped_column(ForeignKey("language_profiles.id"))
    description: Mapped[str | None] = mapped_column(Text)
    active_revision_id: Mapped[str | None] = mapped_column(String, nullable=True)
    language_profile: Mapped[LanguageProfile] = relationship()
    revisions: Mapped[list[PassageRevision]] = relationship(
        back_populates="passage",
        cascade="all, delete-orphan",
        foreign_keys="PassageRevision.passage_id",
    )


class PassageRevision(Base, TimestampMixin):
    __tablename__ = "passage_revisions"
    __table_args__ = (UniqueConstraint("passage_id", "revision_number"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    passage_id: Mapped[str] = mapped_column(ForeignKey("passages.id", ondelete="CASCADE"))
    revision_number: Mapped[int] = mapped_column(Integer)
    source_text: Mapped[str] = mapped_column(Text)
    hierarchy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    practiced: Mapped[bool] = mapped_column(Boolean, default=False)
    passage: Mapped[Passage] = relationship(back_populates="revisions", foreign_keys=[passage_id])
    segments: Mapped[list[Segment]] = relationship(
        back_populates="revision", cascade="all, delete-orphan"
    )


class Segment(Base, TimestampMixin):
    __tablename__ = "segments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    revision_id: Mapped[str] = mapped_column(ForeignKey("passage_revisions.id", ondelete="CASCADE"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String)
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    cue: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    revision: Mapped[PassageRevision] = relationship(back_populates="segments")
    annotations: Mapped[list[Annotation]] = relationship(
        back_populates="segment", cascade="all, delete-orphan"
    )


class Annotation(Base, TimestampMixin):
    __tablename__ = "annotations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    segment_id: Mapped[str] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"))
    layer: Mapped[str] = mapped_column(String)
    value: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    segment: Mapped[Segment] = relationship(back_populates="annotations")


class MediaAsset(Base, TimestampMixin):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("passage_revisions.id", ondelete="CASCADE")
    )
    segment_id: Mapped[str | None] = mapped_column(ForeignKey("segments.id", ondelete="SET NULL"))
    category: Mapped[str] = mapped_column(String)
    mime_type: Mapped[str] = mapped_column(String)
    original_name: Mapped[str] = mapped_column(String)
    storage_path: Mapped[str] = mapped_column(String, unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    cue_points: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )


class ReviewState(Base, TimestampMixin):
    __tablename__ = "review_states"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    segment_id: Mapped[str] = mapped_column(
        ForeignKey("segments.id", ondelete="CASCADE"), unique=True
    )
    fsrs_card_json: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    mastery_stage: Mapped[str] = mapped_column(String, default="new")
    clean_count: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)


class PracticeSession(Base, TimestampMixin):
    __tablename__ = "practice_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    revision_id: Mapped[str] = mapped_column(ForeignKey("passage_revisions.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String, default="active", index=True)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    current_index: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items: Mapped[list[PracticeItem]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="PracticeItem.position"
    )


class PracticeItem(Base, TimestampMixin):
    __tablename__ = "practice_items"
    __table_args__ = (UniqueConstraint("session_id", "position"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("practice_sessions.id", ondelete="CASCADE"))
    segment_id: Mapped[str | None] = mapped_column(ForeignKey("segments.id", ondelete="SET NULL"))
    position: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String)
    prompt: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    session: Mapped[PracticeSession] = relationship(back_populates="items")


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("practice_sessions.id", ondelete="CASCADE"))
    item_id: Mapped[str] = mapped_column(ForeignKey("practice_items.id", ondelete="CASCADE"))
    segment_id: Mapped[str | None] = mapped_column(ForeignKey("segments.id", ondelete="SET NULL"))
    media_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    mode: Mapped[str] = mapped_column(String)
    rating: Mapped[str] = mapped_column(String)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    revealed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PluginManifest(Base, TimestampMixin):
    __tablename__ = "plugin_manifests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    plugin_id: Mapped[str] = mapped_column(String, unique=True)
    kind: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("key", "method", "path"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String)
    method: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    status_code: Mapped[int] = mapped_column(Integer)
    response_json: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
