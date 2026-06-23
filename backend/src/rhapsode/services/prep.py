"""LLM preparation assistant (grill C1/C2).

Strictly prep-side: drafts recall cues, glosses, and translations as ordinary
editable cues/annotations. The practice loop never depends on this module, so
a network outage can never cost a session. Suggestions never overwrite
existing authored content — the LLM drafts, the human owns.

Structured output is enforced by a Pydantic response schema on the Gemini
call plus runtime validation on our side; no string heuristics anywhere.
"""

from collections.abc import Callable
from html import escape
from typing import Any

from pydantic import BaseModel, Field, TypeAdapter, field_validator
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential

from rhapsode import models
from rhapsode.config import get_settings

PREP_LAYERS = ("cue", "gloss", "translation", "reading")


class WordGloss(BaseModel):
    word_index: int
    gloss: str


class TokenSuggestion(BaseModel):
    text: str
    reading: str
    gloss: str = ""

    @field_validator("reading")
    @classmethod
    def require_reading(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("token reading is required")
        return value


class LineSuggestion(BaseModel):
    index: int
    cue: str
    glosses: list[WordGloss] = Field(default_factory=list)
    translation: str
    reading: str = ""
    tokens: list[TokenSuggestion] = Field(default_factory=list)


_suggestions_adapter = TypeAdapter(list[LineSuggestion])


class PrepUnavailableError(RuntimeError):
    pass


def _prompt(language_name: str, lines: list[str]) -> str:
    def line_xml(line_index: int, text: str) -> str:
        words = text.split()
        whitespace_words = ""
        if len(words) > 1:
            whitespace_words = (
                "\n<whitespace_words>\n"
                + "\n".join(
                    f'<word index="{word_index}">{escape(word)}</word>'
                    for word_index, word in enumerate(words)
                )
                + "\n</whitespace_words>"
            )
        return (
            f'<line index="{line_index}">\n'
            f"<text>{escape(text)}</text>"
            f"{whitespace_words}\n"
            "</line>"
        )

    numbered = "\n".join(line_xml(line_index, text) for line_index, text in enumerate(lines))
    return (
        "<task>\n"
        f"For each line of this {language_name} passage being memorized for oral "
        "recitation, draft learner-editable preparation support.\n"
        "</task>\n"
        "<output_contract>\n"
        "Return one object per line with its index and these fields:\n"
        "- cue: a 2-4 word recall cue in the original language, evocative of the "
        "line's content without quoting its opening words\n"
        "- glosses: for lines that include <whitespace_words>, one entry per "
        "non-basic word keyed by that word's index. Each gloss is for a reader "
        "who knows grammar terminology well: lemma, concise morphology, and "
        "meaning, noting anything dialectal, contracted, or elided. Do not repeat "
        "the surface form; the gloss is displayed directly under the word\n"
        "- translation: a natural English translation\n"
        "- reading: a whole-line reading only when that is useful for the language; "
        "for Japanese, use hiragana\n"
        "- tokens: for Japanese and other text whose word boundaries are not encoded "
        "by spaces, split the line into lexical tokens suitable for memorization. "
        "Each token text must be exact surface text from the line, in order; every "
        "Japanese token must include a non-empty hiragana reading, including "
        "kana-only tokens, and token glosses should be concise learner-facing "
        "English. Do not split Japanese into individual characters unless a "
        "character is genuinely an independent token, and do not emit standalone "
        "punctuation tokens\n"
        "</output_contract>\n"
        "<quality_bar>\n"
        "Prefer a few high-signal glosses over exhaustive dictionary noise. Preserve "
        "the original text exactly in token text; the app will reject tokenization "
        "that cannot be reassembled into the line.\n"
        "</quality_bar>\n"
        f"<passage>\n{numbered}\n</passage>"
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=8), reraise=True)
def _generate(language_name: str, lines: list[str]) -> list[LineSuggestion]:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise PrepUnavailableError("GEMINI_API_KEY is not configured.")
    from google import genai

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=_prompt(language_name, lines),
        config={
            "response_mime_type": "application/json",
            "response_schema": list[LineSuggestion],
        },
    )
    return _suggestions_adapter.validate_json(response.text or "[]")


def suggest_prep(
    db: Session,
    revision: models.PassageRevision,
    layers: list[str],
    generate: Callable[[str, list[str]], list[LineSuggestion]] | None = None,
) -> dict[str, int]:
    """Draft prep for every line segment and apply it where nothing authored
    exists yet. Returns counts of what was written, per layer."""
    # Resolved at call time so tests can monkeypatch the module-level hook.
    if generate is None:
        generate = _generate
    lines = sorted(
        (segment for segment in revision.segments if segment.kind == "line"),
        key=lambda segment: segment.ordinal,
    )
    if not lines:
        return {layer: 0 for layer in layers}
    language_name = revision.passage.language_profile.name
    suggestions = {
        suggestion.index: suggestion
        for suggestion in generate(language_name, [line.text for line in lines])
    }
    written = {layer: 0 for layer in layers}
    for index, segment in enumerate(lines):
        suggestion = suggestions.get(index)
        if suggestion is None:
            continue
        if "cue" in layers and not segment.cue and suggestion.cue.strip():
            segment.cue = suggestion.cue.strip()
            written["cue"] += 1
        present_layers = {annotation.layer for annotation in segment.annotations}
        if (
            "translation" in layers
            and "translation" not in present_layers
            and suggestion.translation.strip()
        ):
            _add_annotation(db, segment, "translation", suggestion.translation.strip())
            written["translation"] += 1
        if "gloss" in layers or "reading" in layers:
            layer_counts = _apply_reading_layers(db, revision, segment, suggestion, layers)
            for layer in ("gloss", "reading"):
                if layer in written:
                    written[layer] += layer_counts[layer]
    db.commit()
    return written


def _line_tokens(revision: models.PassageRevision, line: models.Segment) -> list[models.Segment]:
    return sorted(
        (
            segment
            for segment in revision.segments
            if segment.parent_id == line.id and segment.kind == "token"
        ),
        key=lambda segment: segment.ordinal,
    )


def _compact(text: str) -> str:
    return "".join(text.split())


def _suggested_tokens_match_line(
    line: models.Segment, suggestions: list[TokenSuggestion]
) -> bool:
    return bool(suggestions) and _compact("".join(token.text for token in suggestions)) == _compact(
        line.text
    )


def _suggestions_align_tokens(
    tokens: list[models.Segment], suggestions: list[TokenSuggestion]
) -> bool:
    return len(tokens) == len(suggestions) and all(
        _compact(token.text) == _compact(suggestion.text)
        for token, suggestion in zip(tokens, suggestions, strict=True)
    )


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


def _ensure_suggested_tokens(
    db: Session,
    revision: models.PassageRevision,
    line: models.Segment,
    suggestion: LineSuggestion,
) -> list[models.Segment]:
    tokens = _line_tokens(revision, line)
    if tokens or not _suggested_tokens_match_line(line, suggestion.tokens):
        return tokens

    created: list[models.Segment] = []
    for index, token_suggestion in enumerate(suggestion.tokens):
        text = token_suggestion.text.strip()
        if not text:
            continue
        token = models.Segment(
            revision=revision,
            parent_id=line.id,
            kind="token",
            ordinal=index,
            text=text,
            cue=None,
            metadata_json={},
        )
        db.add(token)
        created.append(token)
    db.flush()
    return created


def _apply_reading_layers(
    db: Session,
    revision: models.PassageRevision,
    line: models.Segment,
    suggestion: LineSuggestion,
    layers: list[str],
) -> dict[str, int]:
    """Readings and glosses live on tokens when token boundaries are known.

    The line remains the recall target; token children are support structure for
    interlinear reading, and authored tokenization wins over model output.
    """
    counts = {"gloss": 0, "reading": 0}
    tokens = _ensure_suggested_tokens(db, revision, line, suggestion)
    aligned_token_suggestions = (
        suggestion.tokens if tokens and _suggestions_align_tokens(tokens, suggestion.tokens) else []
    )

    if "reading" in layers and aligned_token_suggestions:
        counts["reading"] += _apply_token_readings(db, tokens, aligned_token_suggestions)
    elif "reading" in layers and not tokens and suggestion.reading.strip() and not _has_layer(
        line, "reading"
    ):
        _add_annotation(
            db,
            line,
            "reading",
            suggestion.reading.strip(),
            {"render": "ruby"},
        )
        counts["reading"] += 1

    if "gloss" not in layers:
        return counts

    if tokens:
        if aligned_token_suggestions:
            counts["gloss"] += _apply_token_glosses(db, tokens, aligned_token_suggestions)
        counts["gloss"] += _apply_word_glosses(db, tokens, suggestion.glosses)
        return counts

    if _has_layer(line, "gloss"):
        return counts
    joined = "; ".join(word.gloss.strip() for word in suggestion.glosses if word.gloss.strip())
    if joined:
        _add_annotation(db, line, "gloss", joined)
        counts["gloss"] += 1
    return counts


def _apply_token_readings(
    db: Session, tokens: list[models.Segment], suggestions: list[TokenSuggestion]
) -> int:
    written = 0
    for token, suggestion in zip(tokens, suggestions, strict=True):
        reading = suggestion.reading.strip()
        if not reading or _has_layer(token, "reading"):
            continue
        _add_annotation(db, token, "reading", reading, {"render": "ruby"})
        written += 1
    return written


def _apply_token_glosses(
    db: Session, tokens: list[models.Segment], suggestions: list[TokenSuggestion]
) -> int:
    written = 0
    for token, suggestion in zip(tokens, suggestions, strict=True):
        gloss = suggestion.gloss.strip()
        if not gloss or _has_layer(token, "gloss"):
            continue
        _add_annotation(db, token, "gloss", gloss)
        written += 1
    return written


def _apply_word_glosses(
    db: Session,
    tokens: list[models.Segment],
    glosses: list[WordGloss],
) -> int:
    written = 0
    for word in glosses:
        if not (0 <= word.word_index < len(tokens)) or not word.gloss.strip():
            continue
        token = tokens[word.word_index]
        if _has_layer(token, "gloss"):
            continue
        _add_annotation(db, token, "gloss", word.gloss.strip())
        written += 1
    return written
