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


def prompt_for(mode: str, target: models.Segment, context: list[models.Segment]) -> dict[str, Any]:
    texts = [segment.text for segment in context]
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
            return {"instruction": "Continue from the cue.", "cue": target.cue or target.text[:12]}
        case "random_start":
            return {"instruction": "Start here and continue.", "start": target.text}
        case "weak_link":
            return {
                "instruction": "Repair this weak link.",
                "cue": target.cue,
                "target_text": target.text,
            }
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
    segments = _ordered_segments(revision, segment_kinds)
    if only_segment_ids is not None:
        segments = [segment for segment in segments if segment.id in only_segment_ids]
    if not segments:
        return []
    stages = {
        state.segment_id: state.mastery_stage
        for state in db.scalars(
            select(models.ReviewState).where(
                models.ReviewState.segment_id.in_([segment.id for segment in segments])
            )
        )
    }
    difficult_ids = _difficult_segment_ids(db)
    modes = {
        segment.id: smart_mode_for(stages.get(segment.id), segment.id in difficult_ids)
        for segment in segments
    }
    # The finisher is appended once every targeted segment graduates —
    # per-segment drilling alone never exercises flow.
    all_graduated = len(segments) > 1 and all(
        stages.get(segment.id) in {"review", "durable"} for segment in segments
    )

    triaged = sorted(
        segments,
        key=lambda segment: (
            _triage_rank(stages.get(segment.id), segment.id in difficult_ids),
            segment.ordinal,
        ),
    )
    if minutes is not None:
        seconds = _mode_seconds(db)
        budget = minutes * 60.0
        # For a fully graduated passage the holistic recitation is the
        # highest-value use of the minutes: budget it FIRST and let per-line
        # maintenance fill the remainder (grill A4).
        if all_graduated:
            budget -= seconds.get(
                PracticeMode.full_passage.value, FALLBACK_MODE_SECONDS
            )
        chosen: list[models.Segment] = []
        for segment in triaged:
            cost = seconds.get(modes[segment.id], FALLBACK_MODE_SECONDS)
            if chosen and budget - cost < 0:
                break
            budget -= cost
            chosen.append(segment)
        segments = chosen
    elif len(segments) > SMART_SESSION_CAP:
        segments = triaged[:SMART_SESSION_CAP]
    # Present the survivors in passage order: verse is memorized in sequence
    # even when triage picked the targets. A juncture shares its ordinal with
    # its landing line and drills first.
    segments = sorted(
        segments, key=lambda segment: (segment.ordinal, segment.kind != "juncture")
    )

    items: list[dict[str, Any]] = []
    for index, target in enumerate(segments):
        mode = modes[target.id]
        items.append(
            {
                "segment_id": target.id,
                "mode": mode,
                "prompt": prompt_for(mode, target, segments[index:]),
            }
        )
    if all_graduated and segments:
        mode = PracticeMode.full_passage.value
        items.append(
            {
                "segment_id": segments[0].id,
                "mode": mode,
                "prompt": prompt_for(mode, segments[0], segments),
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
                    "segment_id": target.id,
                    "mode": mode,
                    "prompt": prompt_for(mode, target, context),
                }
            )
    return items
