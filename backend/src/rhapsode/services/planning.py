from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rhapsode import models
from rhapsode.schemas import PracticeMode

BUILT_IN_MODES = [mode.value for mode in PracticeMode]
PromptBuilder = Callable[[models.Segment, list[models.Segment]], dict[str, Any]]
plugin_mode_builders: dict[str, PromptBuilder] = {}


def register_practice_mode(mode_id: str, builder: PromptBuilder) -> None:
    if mode_id in BUILT_IN_MODES:
        raise ValueError("Plugin practice modes cannot replace built-in modes.")
    plugin_mode_builders[mode_id] = builder


def progressive_masks(text: str) -> list[str]:
    words = text.split()
    if len(words) <= 1:
        return [text, "…"]
    stages = [text]
    for ratio in (0.35, 0.65, 1.0):
        hidden = max(1, round(len(words) * ratio))
        stages.append(" ".join("…" if index < hidden else word for index, word in enumerate(words)))
    return stages


def _lead_in(text: str, words: int = 2) -> str:
    """The first couple of words, verbatim, as a retrieval trigger. Recitation
    is chained — each phrase fires the next — so the most effective cue for
    verbatim recall is the line's own opening, sliced straight from the text so
    diacritics and elided particles stay exact (no LLM paraphrase drift)."""
    return " ".join(text.split()[:words])


def _recall_prompt(
    target: models.Segment, line_instruction: str, hint: str | None
) -> dict[str, Any]:
    """A forward-recall prompt: show the lead-in, recite to the end, then check.
    A juncture's own text is the previous line's tail followed by the next
    line's head, so it already reads as 'lead-in → continue'."""
    if target.kind == "juncture":
        return {
            "instruction": "Recite the line this leads into.",
            "lead_in": target.cue or _lead_in(target.text),
            "target_text": target.text,
        }
    return {
        "instruction": line_instruction,
        "lead_in": _lead_in(target.text),
        # A learner-authored mnemonic is the strongest optional nudge. The
        # revision-owned cue remains the fallback and is never mutated.
        "hint": hint,
        "target_text": target.text,
    }


def prompt_for(
    mode: str,
    target: models.Segment,
    context: list[models.Segment],
    hint: str | None = None,
) -> dict[str, Any]:
    texts = [segment.text for segment in context]
    effective_hint = target.cue if hint is None else hint
    match mode:
        case "shadowing":
            return {"instruction": "Listen, then shadow aloud.", "target_text": target.text}
        case "progressive_fading":
            return {
                "instruction": "Recite as support fades.",
                "stages": progressive_masks(target.text),
            }
        case "forward_chaining":
            return {"instruction": "Recite this growing chain.", "chain": texts}
        case "backward_chaining":
            return {
                "instruction": "Recite this chain into the ending.",
                "chain": list(reversed(texts)),
            }
        case "cue_recall":
            return _recall_prompt(target, "Recite this line to the end.", effective_hint)
        case "random_start":
            return {"instruction": "Start here and continue.", "start": target.text}
        case "weak_link":
            return _recall_prompt(
                target, "This seam keeps tripping you — recite across it.", effective_hint
            )
        case "full_passage":
            return {"instruction": "Recite the full passage from memory.", "blank": True}
        case _:
            if builder := plugin_mode_builders.get(mode):
                return builder(target, context)
            raise ValueError(f"Unknown practice mode: {mode}")


def _practice_kinds(
    revision: models.PassageRevision, segment_kinds: list[str] | None
) -> list[str]:
    """One grain per passage (grill B4): chunks if the revision has them,
    else lines — mixing both would deal the same words twice under two
    review states. Junctures always ride along; they cover the boundaries,
    not the same material."""
    if segment_kinds is not None:
        return segment_kinds
    kinds_present = {segment.kind for segment in revision.segments}
    grain = "chunk" if "chunk" in kinds_present else "line"
    return [grain, "juncture"]


def practiceable_kinds(revision: models.PassageRevision) -> list[str]:
    """The segment kinds that are actual review units for a revision. Word
    tokens exist only to carry interlinear glosses for the reading view; they
    are never drilled, so review states must never accrue to them. Exposing the
    planner's own grain choice keeps the schedulers, the due listing, and
    full-passage grading from disagreeing about what is practiceable (a
    disagreement that otherwise strands the 'Practice N due' button)."""
    return _practice_kinds(revision, None)


def _personal_note_texts(db: Session, segment_ids: list[str]) -> dict[str, str]:
    if not segment_ids:
        return {}
    return dict(
        db.execute(
            select(models.PersonalNote.segment_id, models.PersonalNote.text).where(
                models.PersonalNote.segment_id.in_(segment_ids)
            )
        ).tuples().all()
    )


def _ordered_segments(
    revision: models.PassageRevision, segment_kinds: list[str] | None
) -> list[models.Segment]:
    kinds = _practice_kinds(revision, segment_kinds)
    segments = sorted(
        [segment for segment in revision.segments if segment.kind in kinds],
        # A juncture shares its ordinal with the line it leads into and must
        # drill first: prime the transition, then recall the landing line.
        key=lambda segment: (segment.ordinal, segment.kind != "juncture"),
    )
    if not segments:
        segments = sorted(revision.segments, key=lambda segment: segment.ordinal)
    return segments


# A weak link counts as repaired after this many consecutive cleans since the
# last difficult attempt (grill B1): once could be luck, twice is demonstrated.
REPAIR_STREAK = 2


def _difficult_segment_ids(db: Session) -> set[str]:
    rows = db.execute(
        select(models.Attempt.segment_id, models.Attempt.rating)
        .where(models.Attempt.segment_id.is_not(None))
        .order_by(models.Attempt.created_at)
    )
    cleans_since_difficult: dict[str, int] = {}
    for segment_id, rating in rows:
        if rating in ("incorrect", "revealed"):
            cleans_since_difficult[segment_id] = 0
        elif rating == "clean" and segment_id in cleans_since_difficult:
            cleans_since_difficult[segment_id] += 1
    return {
        segment_id
        for segment_id, cleans in cleans_since_difficult.items()
        if cleans < REPAIR_STREAK
    }


def due_segment_ids(db: Session, segment_ids: list[str]) -> set[str]:
    """Segments whose review state says they are due now (never-reviewed
    segments are not 'due' — they are new and belong to regular sessions)."""
    return set(
        db.scalars(
            select(models.ReviewState.segment_id)
            .where(models.ReviewState.segment_id.in_(segment_ids))
            .where(models.ReviewState.due_at <= datetime.now(UTC))
        )
    )


def smart_mode_for(stage: str | None, difficult: bool) -> str:
    """The coach's mode ladder: support fades as mastery grows. Difficult
    segments get weak_link drilling regardless of stage, except brand-new
    ones which still need scaffolding first."""
    if stage is None or stage == "new":
        return PracticeMode.progressive_fading.value
    if difficult:
        return PracticeMode.weak_link.value
    if stage == "learning":
        return PracticeMode.cue_recall.value
    return PracticeMode.random_start.value


# A smart session must end while momentum lasts. Long passages (epic verse)
# would otherwise emit one item per line and produce unfinishable sessions;
# a capped session is one the user actually completes and comes back from.
SMART_SESSION_CAP = 12

# Cold-start seconds-per-item until personal latency history exists (grill
# A1). Wrong for at most a few sessions; the per-mode means take over once a
# mode has enough samples.
DEFAULT_MODE_SECONDS: dict[str, float] = {
    "shadowing": 30,
    "progressive_fading": 75,
    "forward_chaining": 45,
    "backward_chaining": 45,
    "cue_recall": 20,
    "random_start": 30,
    "weak_link": 35,
    "full_passage": 120,
}
FALLBACK_MODE_SECONDS = 30.0
MIN_MODE_SAMPLES = 5


def _mode_seconds(db: Session) -> dict[str, float]:
    """Personal seconds-per-item by mode, from focused-time attempt latencies."""
    rows = db.execute(
        select(
            models.Attempt.mode,
            func.avg(models.Attempt.latency_ms),
            func.count(models.Attempt.id),
        )
        .where(models.Attempt.latency_ms.is_not(None))
        .group_by(models.Attempt.mode)
    )
    estimates = dict(DEFAULT_MODE_SECONDS)
    for mode, mean_latency_ms, samples in rows:
        if samples >= MIN_MODE_SAMPLES and mean_latency_ms:
            estimates[mode] = float(mean_latency_ms) / 1000.0
    return estimates


def _has_reference_audio(db: Session, revision_id: str) -> bool:
    count = db.scalar(
        select(func.count(models.MediaAsset.id))
        .where(models.MediaAsset.revision_id == revision_id)
        .where(models.MediaAsset.category == "reference")
    )
    return bool(count)


def _triage_rank(stage: str | None, difficult: bool) -> int:
    """When the cap bites, spend the session where it pays most: repair weak
    links, push learning segments, then introduce new material, and only then
    maintain what is already solid."""
    if difficult and stage not in (None, "new"):
        return 0
    if stage == "learning":
        return 1
    if stage is None or stage == "new":
        return 2
    return 3


def build_smart_plan(
    db: Session,
    revision: models.PassageRevision,
    segment_kinds: list[str] | None,
    only_segment_ids: set[str] | None = None,
    minutes: int | None = None,
) -> list[dict[str, Any]]:
    return build_smart_plan_for_revisions(
        db, [revision], segment_kinds, only_segment_ids, minutes
    )


def build_smart_plan_for_revisions(
    db: Session,
    revisions: list[models.PassageRevision],
    segment_kinds: list[str] | None,
    only_segment_ids: set[str] | None = None,
    minutes: int | None = None,
) -> list[dict[str, Any]]:
    revision_segments: list[tuple[models.PassageRevision, list[models.Segment]]] = []
    for revision in revisions:
        segments = _ordered_segments(revision, segment_kinds)
        if only_segment_ids is not None:
            segments = [segment for segment in segments if segment.id in only_segment_ids]
        if segments:
            revision_segments.append((revision, segments))
    all_segments = [segment for _, segments in revision_segments for segment in segments]
    if not all_segments:
        return []
    personal_notes = _personal_note_texts(db, [segment.id for segment in all_segments])
    stages = {
        state.segment_id: state.mastery_stage
        for state in db.scalars(
            select(models.ReviewState).where(
                models.ReviewState.segment_id.in_([segment.id for segment in all_segments])
            )
        )
    }
    difficult_ids = _difficult_segment_ids(db)
    modes = {
        segment.id: smart_mode_for(stages.get(segment.id), segment.id in difficult_ids)
        for segment in all_segments
    }
    # First exposure rides the recording when one exists (grill D2): hear a
    # fluent rendition and speak along BEFORE fading it from memory. Junctures
    # are fragments and don't map onto the audio, so they skip the pass.
    shadow_first: set[str] = set()
    for revision, segments in revision_segments:
        if _has_reference_audio(db, revision.id):
            shadow_first.update(
                segment.id
                for segment in segments
                if stages.get(segment.id) in (None, "new") and segment.kind != "juncture"
            )
    # The finisher is appended once every targeted segment graduates —
    # per-segment drilling alone never exercises flow.
    all_graduated = {
        revision.id: len(segments) > 1
        and all(stages.get(segment.id) in {"review", "durable"} for segment in segments)
        for revision, segments in revision_segments
    }

    triaged = sorted(
        (
            (revision_index, revision, segment)
            for revision_index, (revision, segments) in enumerate(revision_segments)
            for segment in segments
        ),
        key=lambda entry: (
            _triage_rank(stages.get(entry[2].id), entry[2].id in difficult_ids),
            entry[0],
            entry[2].ordinal,
        ),
    )
    chosen: list[tuple[int, models.PassageRevision, models.Segment]] = []
    if minutes is not None:
        seconds = _mode_seconds(db)
        budget = minutes * 60.0
        # For fully graduated passages, holistic recitations are budgeted
        # first. A collection remains one shared budget rather than granting
        # every member passage its own full session allowance.
        for revision, _segments in revision_segments:
            if not all_graduated[revision.id]:
                continue
            budget -= seconds.get(
                PracticeMode.full_passage.value, FALLBACK_MODE_SECONDS
            )
        for entry in triaged:
            segment = entry[2]
            cost = seconds.get(modes[segment.id], FALLBACK_MODE_SECONDS)
            if segment.id in shadow_first:
                cost += seconds.get(
                    PracticeMode.shadowing.value, FALLBACK_MODE_SECONDS
                )
            if chosen and budget - cost < 0:
                break
            budget -= cost
            chosen.append(entry)
    else:
        # The cap limits ITEMS, not segments: a shadowed new segment takes
        # two slots, so a fresh passage with audio still ends while momentum
        # lasts.
        used = 0
        for entry in triaged:
            segment = entry[2]
            weight = 2 if segment.id in shadow_first else 1
            if chosen and used + weight > SMART_SESSION_CAP:
                break
            used += weight
            chosen.append(entry)

    items: list[dict[str, Any]] = []
    # Present survivors in collection-member order and passage order. Each
    # item's revision snapshot keeps full-passage grading scoped correctly.
    for revision, _segments in revision_segments:
        selected = sorted(
            (
                segment
                for _, chosen_revision, segment in chosen
                if chosen_revision.id == revision.id
            ),
            key=lambda segment: (segment.ordinal, segment.kind != "juncture"),
        )
        for index, target in enumerate(selected):
            if target.id in shadow_first:
                shadow = PracticeMode.shadowing.value
                items.append(
                    {
                        "revision_id": revision.id,
                        "segment_id": target.id,
                        "mode": shadow,
                        "prompt": prompt_for(
                            shadow,
                            target,
                            selected[index:],
                            personal_notes.get(target.id, target.cue),
                        ),
                    }
                )
            mode = modes[target.id]
            items.append(
                {
                    "revision_id": revision.id,
                    "segment_id": target.id,
                    "mode": mode,
                    "prompt": prompt_for(
                        mode,
                        target,
                        selected[index:],
                        personal_notes.get(target.id, target.cue),
                    ),
                }
            )
        if all_graduated[revision.id] and selected:
            mode = PracticeMode.full_passage.value
            items.append(
                {
                    "revision_id": revision.id,
                    "segment_id": selected[0].id,
                    "mode": mode,
                    "prompt": prompt_for(
                        mode,
                        selected[0],
                        selected,
                        personal_notes.get(selected[0].id, selected[0].cue),
                    ),
                }
            )
    return items


def build_plan(
    db: Session,
    revision: models.PassageRevision,
    modes: list[str],
    segment_kinds: list[str] | None,
    only_segment_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    segments = _ordered_segments(revision, segment_kinds)
    if only_segment_ids is not None:
        segments = [segment for segment in segments if segment.id in only_segment_ids]
    if not segments:
        return []
    personal_notes = _personal_note_texts(db, [segment.id for segment in segments])
    difficult_ids = _difficult_segment_ids(db)
    items: list[dict[str, Any]] = []
    for mode in modes:
        targets = segments
        if mode == PracticeMode.random_start.value:
            targets = list(segments)
            random.Random(revision.id).shuffle(targets)
        elif mode == PracticeMode.weak_link.value:
            targets = [segment for segment in segments if segment.id in difficult_ids] or segments[
                :1
            ]
        elif mode == PracticeMode.full_passage.value:
            targets = segments[:1]
        for index, target in enumerate(targets):
            context = (
                segments[: index + 1]
                if mode == PracticeMode.forward_chaining.value
                else segments[index:]
            )
            items.append(
                {
                    "revision_id": revision.id,
                    "segment_id": target.id,
                    "mode": mode,
                    "prompt": prompt_for(
                        mode,
                        target,
                        context,
                        personal_notes.get(target.id, target.cue),
                    ),
                }
            )
    return items
