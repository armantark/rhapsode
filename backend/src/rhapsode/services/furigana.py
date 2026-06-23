"""Local Japanese ruby support backed by fugashi + UniDic.

The dictionary gives us a deterministic baseline for furigana without spending
an LLM call. It is still only a baseline: authored readings must win because
lyrics and names often choose non-dictionary readings.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from typing import Any

from sqlalchemy.orm import Session

from rhapsode import models


@dataclass(frozen=True)
class LocalToken:
    text: str
    reading: str | None


def is_japanese_revision(revision: models.PassageRevision) -> bool:
    profile = revision.passage.language_profile
    return profile.slug == "japanese" or profile.name.casefold() == "japanese"


def token_texts(text: str) -> list[str]:
    return [token.text for token in analyze(text)]


def analyze(text: str) -> list[LocalToken]:
    tokens: list[LocalToken] = []
    for word in _tagger()(text):
        surface = str(getattr(word, "surface", word)).strip()
        if not surface:
            continue
        reading = _reading_for_word(word) if _has_kanji(surface) else None
        tokens.append(LocalToken(text=surface, reading=reading))
    return tokens


def reading_for_text(text: str) -> str | None:
    if not _has_kanji(text):
        return None
    reading = "".join(token.reading or token.text for token in analyze(text)).strip()
    return reading or None


def apply_local_readings(db: Session, revision: models.PassageRevision) -> int:
    """Create/fill Japanese token ruby readings for every line in a revision."""
    if not is_japanese_revision(revision):
        return 0

    written = 0
    for line in _lines(revision):
        tokens = _tokens(revision, line)
        if not tokens:
            local_tokens = analyze(line.text)
            if not any(token.reading for token in local_tokens):
                continue
            tokens = _create_tokens(db, revision, line, local_tokens)
        written += _fill_token_readings(db, tokens)
    return written


def _tagger() -> Any:
    return _cached_tagger()


@lru_cache(maxsize=1)
def _cached_tagger() -> Any:
    return import_module("fugashi").Tagger()


def _reading_for_word(word: Any) -> str | None:
    feature = getattr(word, "feature", None)
    reading = getattr(feature, "kana", None) or getattr(feature, "pron", None)
    if not isinstance(reading, str) or reading == "*":
        return None
    return _katakana_to_hiragana(reading)


def _katakana_to_hiragana(text: str) -> str:
    return "".join(chr(ord(char) - 0x60) if "\u30a1" <= char <= "\u30f6" else char for char in text)


def _has_kanji(text: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in text)


def _lines(revision: models.PassageRevision) -> list[models.Segment]:
    return sorted(
        (segment for segment in revision.segments if segment.kind == "line"),
        key=lambda segment: segment.ordinal,
    )


def _tokens(
    revision: models.PassageRevision, line: models.Segment
) -> list[models.Segment]:
    return sorted(
        (
            segment
            for segment in revision.segments
            if segment.parent_id == line.id and segment.kind == "token"
        ),
        key=lambda segment: segment.ordinal,
    )


def _create_tokens(
    db: Session,
    revision: models.PassageRevision,
    line: models.Segment,
    tokens: Iterable[LocalToken],
) -> list[models.Segment]:
    created: list[models.Segment] = []
    for index, token in enumerate(tokens):
        segment = models.Segment(
            revision=revision,
            parent_id=line.id,
            kind="token",
            ordinal=index,
            text=token.text,
            cue=None,
            metadata_json={"source": "local_furigana"},
        )
        db.add(segment)
        created.append(segment)
    db.flush()
    return created


def _fill_token_readings(db: Session, tokens: list[models.Segment]) -> int:
    written = 0
    for token in tokens:
        if _has_layer(token, "reading"):
            continue
        reading = reading_for_text(token.text)
        if not reading:
            continue
        _add_annotation(db, token, "reading", reading, {"render": "ruby"})
        written += 1
    return written


def _has_layer(segment: models.Segment, layer: str) -> bool:
    return any(annotation.layer == layer for annotation in segment.annotations)


def _add_annotation(
    db: Session,
    segment: models.Segment,
    layer: str,
    value: str,
    data: dict[str, Any] | None = None,
) -> None:
    annotation = models.Annotation(
        segment_id=segment.id,
        layer=layer,
        value=value,
        data=data or {},
    )
    db.add(annotation)
    segment.annotations.append(annotation)
