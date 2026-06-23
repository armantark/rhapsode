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


@dataclass(frozen=True)
class _TaggedToken:
    text: str
    reading: str | None
    pos1: str
    pos2: str
    pos3: str


def is_japanese_revision(revision: models.PassageRevision) -> bool:
    profile = revision.passage.language_profile
    return profile.slug == "japanese" or profile.name.casefold() == "japanese"


def token_texts(text: str) -> list[str]:
    return [token.text for token in analyze(text)]


def analyze(text: str) -> list[LocalToken]:
    tagged: list[_TaggedToken] = []
    for word in _tagger()(text):
        surface = str(getattr(word, "surface", word)).strip()
        if not surface or _is_punctuation_only(surface):
            continue
        feature = getattr(word, "feature", None)
        tagged.append(
            _TaggedToken(
                text=surface,
                reading=_reading_for_word(word),
                pos1=_feature_part(feature, "pos1"),
                pos2=_feature_part(feature, "pos2"),
                pos3=_feature_part(feature, "pos3"),
            )
        )
    return [
        LocalToken(text=token.text, reading=token.reading if _has_kanji(token.text) else None)
        for token in _merge_learner_tokens(tagged)
    ]


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
    for line in _ruby_targets(revision):
        inherited_readings = _landing_line_readings(revision, line)
        tokens = _tokens(revision, line)
        if not tokens:
            local_tokens = analyze(line.text)
            if not any(token.reading for token in local_tokens):
                continue
            tokens = _create_tokens(db, revision, line, local_tokens)
        written += _fill_token_readings(db, tokens, inherited_readings)
    return written


def retokenize_revision(db: Session, revision: models.PassageRevision) -> dict[str, int]:
    """Replace Japanese ruby token children with the current local tokenizer.

    This is for repairing old revisions whose token boundaries came from an
    earlier prompt/local-tokenizer contract. It deliberately preserves existing
    exact-surface ruby readings, because song lyrics often need readings the
    dictionary cannot infer (`水面` as `みなも`, `運命` as `さだめ`).
    """
    if not is_japanese_revision(revision):
        return {"targets": 0, "deleted": 0, "created": 0, "readings": 0}

    stats = {"targets": 0, "deleted": 0, "created": 0, "readings": 0}
    for target in _ruby_targets(revision):
        local_tokens = analyze(target.text)
        if not local_tokens:
            continue
        old_tokens = _tokens(revision, target)
        preserved = {
            **_preserved_readings(old_tokens, local_tokens),
            **_landing_line_readings(revision, target),
        }
        for token in old_tokens:
            db.delete(token)
        db.flush()
        created = _create_tokens(db, revision, target, local_tokens)
        for token, local in zip(created, local_tokens, strict=True):
            reading = preserved.get(token.text) or local.reading
            if reading and _has_kanji(token.text):
                _add_annotation(db, token, "reading", reading, {"render": "ruby"})
                stats["readings"] += 1
        stats["targets"] += 1
        stats["deleted"] += len(old_tokens)
        stats["created"] += len(created)
    return stats


def _preserved_readings(
    old_tokens: list[models.Segment], local_tokens: list[LocalToken]
) -> dict[str, str]:
    exact = {
        token.text: reading
        for token in old_tokens
        if (reading := _reading_annotation(token)) and _has_kanji(token.text)
    }
    preserved: dict[str, str] = {}
    for local in local_tokens:
        if local.text in exact:
            preserved[local.text] = exact[local.text]
            continue
        if not _has_kanji(local.text):
            continue
        for start in range(len(old_tokens)):
            collected: list[models.Segment] = []
            text = ""
            for token in old_tokens[start:]:
                collected.append(token)
                text += token.text
                if text == local.text:
                    reading = "".join(
                        _reading_annotation(item) or item.text for item in collected
                    )
                    if reading:
                        preserved[local.text] = reading
                    break
                if len(text) >= len(local.text):
                    break
            if local.text in preserved:
                break
    return preserved


def _reading_annotation(token: models.Segment) -> str | None:
    for annotation in token.annotations:
        if annotation.layer == "reading" and annotation.data.get("render") == "ruby":
            return annotation.value
    return None


def _landing_line_readings(
    revision: models.PassageRevision, target: models.Segment
) -> dict[str, str]:
    if target.kind != "juncture":
        return {}
    line = next(
        (
            segment
            for segment in revision.segments
            if segment.kind == "line" and segment.ordinal == target.ordinal
        ),
        None,
    )
    if line is None:
        return {}
    return {
        token.text: reading
        for token in _tokens(revision, line)
        if (reading := _reading_annotation(token)) and _has_kanji(token.text)
    }


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


def _feature_part(feature: Any, name: str) -> str:
    value = getattr(feature, name, "")
    return value if isinstance(value, str) else ""


def _merge_learner_tokens(tokens: list[_TaggedToken]) -> list[_TaggedToken]:
    merged: list[_TaggedToken] = []
    for token in tokens:
        if merged and _continues_previous_token(token):
            previous = merged[-1]
            merged[-1] = _TaggedToken(
                text=previous.text + token.text,
                reading=_merged_reading(previous, token),
                pos1=previous.pos1,
                pos2=previous.pos2,
                pos3=previous.pos3,
            )
        else:
            merged.append(token)
    return merged


def _continues_previous_token(token: _TaggedToken) -> bool:
    return (
        token.pos1 == "助動詞"
        or token.pos1 == "接尾辞"
        or (token.pos1 == "助詞" and token.pos2 == "接続助詞")
        or (token.pos1 == "動詞" and token.pos2 == "非自立可能")
    )


def _merged_reading(previous: _TaggedToken, token: _TaggedToken) -> str | None:
    if not _has_kanji(previous.text + token.text):
        return None
    return (previous.reading or previous.text) + (token.reading or token.text)


def _katakana_to_hiragana(text: str) -> str:
    return "".join(chr(ord(char) - 0x60) if "\u30a1" <= char <= "\u30f6" else char for char in text)


def _has_kanji(text: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in text)


def _is_punctuation_only(text: str) -> bool:
    return not any(char.isalnum() for char in text)


def _ruby_targets(revision: models.PassageRevision) -> list[models.Segment]:
    return sorted(
        (segment for segment in revision.segments if segment.kind in {"line", "juncture"}),
        key=lambda segment: (segment.kind == "juncture", segment.ordinal),
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


def _fill_token_readings(
    db: Session, tokens: list[models.Segment], inherited_readings: dict[str, str] | None = None
) -> int:
    written = 0
    inherited_readings = inherited_readings or {}
    for token in tokens:
        if _has_layer(token, "reading"):
            continue
        reading = inherited_readings.get(token.text) or reading_for_text(token.text)
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
