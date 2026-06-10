from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
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


def _ordered_segments(
    revision: models.PassageRevision, segment_kinds: list[str]
) -> list[models.Segment]:
    segments = sorted(
        [segment for segment in revision.segments if segment.kind in segment_kinds],
        key=lambda segment: segment.ordinal,
    )
    if not segments:
        segments = sorted(revision.segments, key=lambda segment: segment.ordinal)
    return segments


def _difficult_segment_ids(db: Session) -> set[str]:
    return {
        row[0]
        for row in db.execute(
            select(models.Attempt.segment_id)
            .where(models.Attempt.rating.in_(["incorrect", "revealed"]))
            .where(models.Attempt.segment_id.is_not(None))
        )
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
    segment_kinds: list[str],
    only_segment_ids: set[str] | None = None,
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
    if len(segments) > SMART_SESSION_CAP:
        chosen = sorted(
            segments,
            key=lambda segment: (
                _triage_rank(stages.get(segment.id), segment.id in difficult_ids),
                segment.ordinal,
            ),
        )[:SMART_SESSION_CAP]
        # Present the survivors in passage order: verse is memorized in
        # sequence even when triage picked the targets.
        segments = sorted(chosen, key=lambda segment: segment.ordinal)
    items: list[dict[str, Any]] = []
    for index, target in enumerate(segments):
        mode = smart_mode_for(stages.get(target.id), target.id in difficult_ids)
        items.append(
            {
                "segment_id": target.id,
                "mode": mode,
                "prompt": prompt_for(mode, target, segments[index:]),
            }
        )
    # Once every targeted segment has graduated past learning, close with one
    # holistic recitation — per-segment drilling alone never exercises flow.
    all_graduated = len(segments) > 1 and all(
        stages.get(segment.id) in {"review", "durable"} for segment in segments
    )
    if all_graduated:
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
    segment_kinds: list[str],
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
