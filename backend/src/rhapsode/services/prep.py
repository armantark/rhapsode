"""LLM preparation assistant (grill C1/C2).

Strictly prep-side: drafts recall cues, glosses, and translations as ordinary
editable cues/annotations. The practice loop never depends on this module, so
a network outage can never cost a session. Suggestions never overwrite
existing authored content — the LLM drafts, the human owns.

Structured output is enforced by a Pydantic response schema on the Gemini
call plus runtime validation on our side; no string heuristics anywhere.
"""

from collections.abc import Callable

from pydantic import BaseModel, TypeAdapter
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential

from rhapsode import models
from rhapsode.config import get_settings

PREP_LAYERS = ("cue", "gloss", "translation")


class LineSuggestion(BaseModel):
    index: int
    cue: str
    gloss: str
    translation: str


_suggestions_adapter = TypeAdapter(list[LineSuggestion])


class PrepUnavailableError(RuntimeError):
    pass


def _prompt(language_name: str, lines: list[str]) -> str:
    numbered = "\n".join(
        f'<line index="{index}">{text}</line>' for index, text in enumerate(lines)
    )
    return (
        "<task>\n"
        f"For each line of this {language_name} passage being memorized for oral "
        "recitation, provide:\n"
        "- cue: a 2-4 word recall cue in the original language, evocative of the "
        "line's content without quoting its opening words\n"
        "- gloss: a philological gloss for the reader, who knows grammar "
        "terminology well. Cover each word that is not basic vocabulary, in the "
        "order it appears, as: surface form, then an em dash, then lemma, "
        "concise morphological parse, and meaning. Separate entries with " 
        "semicolons. Note anything dialectal, contracted, or elided\n"
        "- translation: a natural English translation\n"
        "Return one object per line with its index.\n"
        "</task>\n"
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
        for layer, value in (
            ("gloss", suggestion.gloss),
            ("translation", suggestion.translation),
        ):
            if layer in layers and layer not in present_layers and value.strip():
                db.add(
                    models.Annotation(
                        segment_id=segment.id, layer=layer, value=value.strip()
                    )
                )
                written[layer] += 1
    db.commit()
    return written
