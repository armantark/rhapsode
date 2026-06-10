from __future__ import annotations

import random
from collections.abc import Callable
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


def build_plan(
    db: Session,
    revision: models.PassageRevision,
    modes: list[str],
    segment_kinds: list[str],
) -> list[dict[str, Any]]:
    segments = sorted(
        [segment for segment in revision.segments if segment.kind in segment_kinds],
        key=lambda segment: segment.ordinal,
    )
    if not segments:
        segments = sorted(revision.segments, key=lambda segment: segment.ordinal)
    difficult_ids = {
        row[0]
        for row in db.execute(
            select(models.Attempt.segment_id)
            .where(models.Attempt.rating.in_(["incorrect", "revealed"]))
            .where(models.Attempt.segment_id.is_not(None))
        )
    }
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
