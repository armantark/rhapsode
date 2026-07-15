from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable, Mapping
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
    if len(words) > 1:
        units = words
        joiner = " "
    else:
        units = [char for char in text if not char.isspace()]
        joiner = ""
    # Support fades from the END toward the opening: the opening is the
    # retrieval cue (see _lead_in), so each stage asks for a longer recalled
    # tail and the last supported stage converges on the cue_recall card the
    # ladder graduates to. Ellipsis units are continuation markers on juncture
    # heads, not content, so they are never masked.
    maskable = [index for index, unit in enumerate(units) if unit != "…"]
    if len(maskable) <= 1:
        return [text, _mask_units(units, set(maskable), joiner)]
    stages = [text]
    for hidden in _progressive_hidden_counts(len(maskable)):
        stages.append(_mask_units(units, set(maskable[len(maskable) - hidden :]), joiner))
    return stages


def _mask_units(units: list[str], hidden: set[int], joiner: str) -> str:
    return joiner.join(
        _dot_mask(unit) if index in hidden else unit for index, unit in enumerate(units)
    )


def _progressive_hidden_counts(total: int) -> list[int]:
    return sorted({max(1, round(total * ratio)) for ratio in (0.25, 0.5, 0.75, 1.0)})


def _dot_mask(text: str) -> str:
    return "".join("•" if not char.isspace() else char for char in text)


def _lead_in(target: models.Segment, words: int = 2) -> str:
    """The first couple of tokens, verbatim, as a retrieval trigger. Recitation
    is chained — each phrase fires the next — so the most effective cue for
    verbatim recall is the line's own opening, sliced straight from the segment
    tree so Japanese does not collapse into a whole-line cue."""
    tokens = _token_children(target)
    if tokens:
        # Rejoin tokens with the line's own word separator: spaced scripts
        # (Greek, Latin) need the spaces back, or the opening smushes into one
        # run ("μῆνινἄειδε"); Japanese and other unspaced text join with "".
        joiner = " " if any(char.isspace() for char in target.text) else ""
        return joiner.join(token.text for token in tokens[:words])
    return " ".join(target.text.split()[:words])


def _token_children(target: models.Segment) -> list[models.Segment]:
    revision = target.revision
    if revision is None:
        return []
    return sorted(
        (
            segment
            for segment in revision.segments
            if segment.parent_id == target.id and segment.kind == "token"
        ),
        key=lambda segment: segment.ordinal,
    )


def _recall_units(target: models.Segment) -> list[str]:
    tokens = _token_children(target)
    if tokens:
        return [token.text for token in tokens]
    return [word for word in target.text.split() if word != "…"]


def _recall_prompt(
    target: models.Segment, line_instruction: str, hint: str | None
) -> dict[str, Any]:
    """A forward-recall prompt: show the lead-in, recite to the end, then check.
    A juncture's own text is the previous line's tail followed by the next
    line's head, so it already reads as 'lead-in → continue'."""
    if target.kind == "juncture":
        # A juncture's text is the next line's head: its first JUNCTURE_SPAN
        # words plus an ellipsis. "Opening" left the stop point ambiguous, so we
        # name the exact word count — the one mode that stops mid-line needs the
        # clearest endpoint of all.
        count = len(_recall_units(target))
        plural = "s" if count != 1 else ""
        return {
            "instruction": (
                "Carry on into the next line — recite just its first "
                f"{count} word{plural}, then stop."
            ),
            "lead_in": target.cue or _lead_in(target),
            "target_text": target.text,
        }
    return {
        "instruction": line_instruction,
        "lead_in": _lead_in(target),
        # A learner-authored mnemonic is the strongest optional nudge. The
        # revision-owned cue remains the fallback and is never mutated.
        "hint": hint,
        "target_text": target.text,
    }


def _shuffled_units(units: list[str]) -> list[str]:
    """Shuffle without ever dealing the natural order (mirrors _random_start_order)."""
    shuffled = list(units)
    if len(shuffled) < 2:
        return shuffled
    for _ in range(5):
        random.shuffle(shuffled)
        if shuffled != units:
            return shuffled
    return shuffled[1:] + shuffled[:1]


def _word_bank_prompt(target: models.Segment) -> dict[str, Any]:
    """Rebuild-the-line: every unit is given, only the ORDER must be recalled.
    Serial order is the dominant failure in verse recitation, and with all
    items dealt the difficulty sits just above fading — the early rung of the
    ladder before full production is asked for."""
    return {
        "instruction": "Rebuild the line: arrange every word in order, then check.",
        "word_bank": _shuffled_units(_recall_units(target)),
        "target_text": target.text,
    }


def _acquisition_prompt(target: models.Segment, hint: str | None) -> dict[str, Any]:
    """One criterion-based first lesson for a line: encounter the exact text,
    reconstruct supplied recall units, then transfer to lead-in-only oral
    production. Segment annotations and reference audio remain available via
    the practice card's existing revision context rather than being copied into
    persisted prompt JSON."""
    return {
        "instruction": "Learn this line, rebuild it, then produce it from its opening.",
        "target_text": target.text,
        "word_bank": _shuffled_units(_recall_units(target)),
        "lead_in": _lead_in(target),
        "hint": hint,
    }


def _typed_recall_prompt(target: models.Segment, hint: str | None) -> dict[str, Any]:
    """Typed recall: the forward-recall shape of cue_recall, but production is
    written, so every character (accents, breathings, okurigana) demands a
    commitment the ear lets slide past. The check is a stacked visual
    comparison the learner judges — never an automated matcher; self-grading
    stays the instrument (grill D3)."""
    if target.kind == "juncture":
        count = len(_recall_units(target))
        plural = "s" if count != 1 else ""
        return {
            "instruction": (
                "Carry on in writing — type just the next line's first "
                f"{count} word{plural}, then check."
            ),
            "lead_in": target.cue or _lead_in(target),
            "target_text": target.text,
        }
    return {
        "instruction": "Type this line from memory to the end, then check.",
        "lead_in": _lead_in(target),
        "hint": hint,
        "target_text": target.text,
    }


def _translation_text(target: models.Segment) -> str | None:
    for annotation in target.annotations:
        if annotation.layer == "translation" and annotation.value.strip():
            return annotation.value.strip()
    return None


def _meaning_recall_prompt(target: models.Segment) -> dict[str, Any]:
    """Meaning-cued recall: the drafted translation is the prompt and the
    original is the answer, exercising the meaning→form mapping that serial
    rote leaves untouched — the decay mode where a passage becomes sound
    without sense. Only lines with a translation annotation qualify."""
    return {
        "instruction": "The meaning is shown — recite the original line to the end.",
        "translation": _translation_text(target) or "",
        "target_text": target.text,
    }


# Juncture recall cards can substitute the cue's MODALITY when aligned
# reference audio exists: hearing the previous line is the actual performance
# condition, so these modes carry an audio_cue span alongside the text lead-in.
JUNCTURE_AUDIO_CUE_MODES = {
    PracticeMode.progressive_fading.value,
    PracticeMode.cue_recall.value,
    PracticeMode.typed_recall.value,
    PracticeMode.random_start.value,
    PracticeMode.weak_link.value,
}


def _reference_cue_spans(db: Session, revision_id: str) -> dict[str, dict[str, Any]]:
    """segment_id → {media_id, start, end} from aligned reference audio."""
    spans: dict[str, dict[str, Any]] = {}
    for asset in db.scalars(
        select(models.MediaAsset)
        .where(models.MediaAsset.revision_id == revision_id)
        .where(models.MediaAsset.category == "reference")
        .order_by(models.MediaAsset.created_at)
    ):
        for cue in asset.cue_points or []:
            segment_id = cue.get("segment_id")
            end = cue.get("end")
            if segment_id and end is not None and segment_id not in spans:
                spans[segment_id] = {
                    "media_id": asset.id,
                    "start": cue.get("time", 0.0),
                    "end": end,
                }
    return spans


def _attach_juncture_audio_cue(
    prompt: dict[str, Any],
    mode: str,
    target: models.Segment,
    spans: Mapping[str, dict[str, Any]],
    lines_by_ordinal: Mapping[int, models.Segment],
) -> None:
    if not spans or target.kind != "juncture" or mode not in JUNCTURE_AUDIO_CUE_MODES:
        return
    previous_ordinal = (target.metadata_json or {}).get("juncture_after")
    line = lines_by_ordinal.get(previous_ordinal) if isinstance(previous_ordinal, int) else None
    if line is None:
        return
    cue = spans.get(line.id)
    if cue:
        prompt["audio_cue"] = cue


def _range_label(
    start: int, end: int, context: list[models.Segment] | None = None
) -> str:
    references = [segment.reference_label for segment in (context or [])]
    if references and all(references):
        if len(references) == 1:
            return references[0] or ""
        return f"{references[0]} through {references[-1]}"
    if start == end:
        return f"line {start} in this passage"
    return f"lines {start}-{end} in this passage"


def _chain_prompt(
    context: list[models.Segment], line_numbers: list[int] | None = None
) -> dict[str, Any]:
    numbers = line_numbers or list(range(1, len(context) + 1))
    start = numbers[0] if numbers else 1
    end = numbers[-1] if numbers else start
    label = _range_label(start, end, context)
    return {
        "instruction": f"From memory, recite {label}, then check.",
        "chain": [segment.text for segment in context],
        "chain_segment_ids": [segment.id for segment in context],
        "chain_reference_labels": [segment.reference_label for segment in context],
        "line_start": start,
        "line_end": end,
        "prefix_length": end,
        "range_label": label,
    }


def prompt_for(
    mode: str,
    target: models.Segment,
    context: list[models.Segment],
    hint: str | None = None,
    line_numbers: list[int] | None = None,
) -> dict[str, Any]:
    effective_hint = target.cue if hint is None else hint
    match mode:
        case "shadowing":
            return {
                "instruction": "Listen, then shadow the whole line aloud.",
                "target_text": target.text,
            }
        case "acquisition":
            return _acquisition_prompt(target, effective_hint)
        case "progressive_fading":
            # A juncture is the next line's head, not a whole line, so its fading
            # drill stops at the head rather than running to a line end. The
            # association being trained is tail→head, so the previous line's
            # tail rides along as a persistent lead-in — without it, the final
            # faded stage asks for "the next line's opening" with no indication
            # of which transition is being crossed.
            if target.kind == "juncture":
                prompt: dict[str, Any] = {
                    "instruction": "Recite the next line's opening as the support fades.",
                    "stages": progressive_masks(target.text),
                }
                if target.cue:
                    prompt["lead_in"] = target.cue
                return prompt
            return {
                "instruction": "Recite the whole line to the end as the support fades.",
                "stages": progressive_masks(target.text),
            }
        case "word_bank":
            return _word_bank_prompt(target)
        case "typed_recall":
            return _typed_recall_prompt(target, effective_hint)
        case "meaning_recall":
            return _meaning_recall_prompt(target)
        case "forward_chaining":
            return _chain_prompt(context, line_numbers)
        case "backward_chaining":
            return _chain_prompt(context, line_numbers)
        case "cue_recall":
            return _recall_prompt(target, "Recite this line to the end.", effective_hint)
        case "random_start":
            # A drop-in cold start: this line is reached WITHOUT its usual run-up,
            # to break the serial-order dependence that lets you recite a passage
            # top-to-bottom yet freeze if dropped in the middle. Same checkable
            # recall shape as cue_recall (lead-in shown, full line revealed to
            # check) but framed as an arbitrary entry point with a clear endpoint.
            return _recall_prompt(
                target, "Dropped in at a random line — recite it to the end.", effective_hint
            )
        case "weak_link":
            return _recall_prompt(
                target,
                "This seam keeps tripping you — recite the line across it to the end.",
                effective_hint,
            )
        case "full_passage":
            return {
                "instruction": "Recite the whole passage from memory, start to finish.",
                "blank": True,
            }
        case "recital":
            # A performance card: no checks, no reveal, no grade bar. The only
            # interaction is flagging stumbles by line number; the confirm
            # screen turns the map into per-line grades (see submit_attempt).
            return {
                "instruction": (
                    "Perform the whole passage from memory, start to finish — "
                    "tap a line's number the moment you stumble, then confirm the map."
                ),
                "blank": True,
            }
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


def _random_start_order(targets: list[models.Segment]) -> list[models.Segment]:
    """Shuffle cold-start targets without ever falling back to plain passage order."""
    shuffled = list(targets)
    if len(shuffled) < 2:
        return shuffled
    natural_order = [segment.id for segment in shuffled]
    for _ in range(5):
        random.shuffle(shuffled)
        if [segment.id for segment in shuffled] != natural_order:
            return shuffled
    return shuffled[1:] + shuffled[:1]


def _shuffle_random_start_turns(
    turns: list[tuple[models.Segment, str]],
) -> list[tuple[models.Segment, str]]:
    random_targets = [
        target for target, mode in turns if mode == PracticeMode.random_start.value
    ]
    if len(random_targets) < 2:
        return turns
    shuffled_targets = iter(_random_start_order(random_targets))
    return [
        (next(shuffled_targets), mode)
        if mode == PracticeMode.random_start.value
        else (target, mode)
        for target, mode in turns
    ]


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


def smart_mode_for(
    stage: str | None,
    difficult: bool,
    *,
    kind: str = "line",
    mode_counts: dict[str, int] | None = None,
    has_reference_audio: bool = False,
    has_translation: bool = False,
    acquisition_succeeded: bool | None = None,
    last_rating: str | None = None,
    last_mode: str | None = None,
    has_chain_context: bool = False,
) -> str:
    """Choose the least-used useful exercise for this mastery stage.

    Triage still decides *which* segments deserve attention. Within a selected
    line, rotating techniques prevents "weak link" from becoming the only way
    difficult material is ever practiced. Junctures keep a narrower repertoire
    because chaining a transition fragment is not a coherent exercise.
    """
    acquired = (
        stage not in (None, "new")
        if acquisition_succeeded is None
        else acquisition_succeeded
    )
    if not acquired:
        # A three-word juncture head does not benefit from chip ordering; keep
        # its established progressive tail→head lesson. Whole lines receive
        # the composite criterion-based acquisition card.
        return (
            PracticeMode.progressive_fading.value
            if kind == "juncture"
            else PracticeMode.acquisition.value
        )
    if last_rating in {"revealed", "incorrect"}:
        # A recent lapse restores support before any cold weak-link drill. Once
        # this supported turn is graded, normal least-used rotation resumes.
        return (
            PracticeMode.progressive_fading.value
            if kind == "juncture"
            else PracticeMode.word_bank.value
        )
    if kind != "juncture" and last_mode == PracticeMode.acquisition.value:
        # The first return after acquisition is response-contingent rather than
        # another arbitrary turn through the rotation. A hesitant success needs
        # a clean cue-only retrieval; a clean success can begin passage flow as
        # soon as a learned predecessor makes chaining a real exercise.
        if last_rating == "hesitant":
            return PracticeMode.cue_recall.value
        if last_rating == "clean":
            return (
                PracticeMode.forward_chaining.value
                if has_chain_context
                else PracticeMode.cue_recall.value
            )
    if kind == "juncture":
        # Junctures skip word_bank (a 3-word head makes ordering trivial) but
        # graduate to a typed bridge: writing the landing words pins them.
        cycle = (
            [PracticeMode.cue_recall.value, PracticeMode.progressive_fading.value]
            if stage == "learning"
            else [
                PracticeMode.random_start.value,
                PracticeMode.cue_recall.value,
                PracticeMode.typed_recall.value,
            ]
        )
    elif stage == "learning":
        # word_bank leads the learning cycle: all units are given, only order
        # is recalled, so it is the gentlest step up from fading before full
        # production (cue recall, chaining) is asked for.
        cycle = [
            PracticeMode.word_bank.value,
            PracticeMode.cue_recall.value,
            PracticeMode.forward_chaining.value,
            PracticeMode.backward_chaining.value,
            PracticeMode.progressive_fading.value,
        ]
    else:
        # Graduated lines earn typed recall: written production verifies the
        # character-level exactness oral self-grading cannot hear.
        cycle = [
            PracticeMode.random_start.value,
            PracticeMode.typed_recall.value,
            PracticeMode.forward_chaining.value,
            PracticeMode.backward_chaining.value,
            PracticeMode.cue_recall.value,
        ]
    if has_reference_audio and kind != "juncture" and (stage == "learning" or difficult):
        cycle.append(PracticeMode.shadowing.value)
    # Meaning-cued recall gates on a drafted translation the way shadowing
    # gates on reference audio, and joins only the graduated repertoire —
    # producing form from a semantic cue presumes the form is already learned.
    if has_translation and kind != "juncture" and stage != "learning":
        cycle.append(PracticeMode.meaning_recall.value)
    if difficult:
        cycle = [PracticeMode.weak_link.value, *cycle]
    counts = mode_counts or {}
    return min(cycle, key=lambda mode: (counts.get(mode, 0), cycle.index(mode)))


# A smart session must end while momentum lasts. Long passages (epic verse)
# would otherwise emit one item per line and produce unfinishable sessions;
# a capped session is one the user actually completes and comes back from.
SMART_SESSION_CAP = 12

# When a minutes budget is chosen it is a TARGET, not just a ceiling: once every
# targeted segment has had its primary turn and time remains (a short passage
# can't otherwise fill 15 minutes), the leftover budget buys extra repetitions
# that walk this rotation. It is ordered most-to-least support so repeats fade
# scaffolding rather than re-dealing one exercise, and a segment's own primary
# mode is skipped so the first repeat always varies the retrieval. The rotation
# length also caps reps per segment, which stops a tiny passage from being
# ground to death when a long budget is picked.
FILL_MODE_CYCLE = [
    PracticeMode.progressive_fading.value,
    PracticeMode.word_bank.value,
    PracticeMode.forward_chaining.value,
    PracticeMode.backward_chaining.value,
    PracticeMode.cue_recall.value,
    PracticeMode.random_start.value,
]

# Cold-start seconds-per-item until personal latency history exists (grill
# A1). Wrong for at most a few sessions; the per-mode means take over once a
# mode has enough samples.
DEFAULT_MODE_SECONDS: dict[str, float] = {
    "shadowing": 30,
    "acquisition": 90,
    "progressive_fading": 75,
    "word_bank": 40,
    "forward_chaining": 45,
    "backward_chaining": 45,
    "cue_recall": 20,
    "typed_recall": 60,
    "meaning_recall": 25,
    "random_start": 30,
    "weak_link": 35,
    "full_passage": 120,
    "recital": 120,
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


def _triage_rank(stage: str | None, difficult: bool, due: bool) -> int:
    """When the cap bites, spend the session where it pays most: repair weak
    links, push learning segments, then service DUE reviews (their memory is
    decaying now), then introduce new material, and only then maintain solid
    lines that are not yet due — the spaced-repetition "reviews before new"
    rule, so a long budget doesn't crowd due maintenance out with novelty."""
    if difficult and stage not in (None, "new"):
        return 0
    if stage == "learning":
        return 1
    if stage is None or stage == "new":
        return 3
    return 2 if due else 4


def _line_segments(segments: list[models.Segment]) -> list[models.Segment]:
    return [segment for segment in segments if segment.kind == "line"]


def _line_number_map(segments: list[models.Segment]) -> dict[str, int]:
    return {segment.id: index for index, segment in enumerate(_line_segments(segments), start=1)}


def _line_numbers(
    context: list[models.Segment], line_numbers_by_id: dict[str, int]
) -> list[int] | None:
    numbers = [line_numbers_by_id.get(segment.id) for segment in context]
    if any(number is None for number in numbers):
        return None
    return [number for number in numbers if number is not None]


def _started_stage(stage: str | None) -> bool:
    return stage not in (None, "new")


def _learned_prefix(
    lines: list[models.Segment],
    stages: Mapping[str, str | None],
) -> list[models.Segment]:
    prefix: list[models.Segment] = []
    for line in lines:
        if _started_stage(stages.get(line.id)):
            prefix.append(line)
            continue
        break
    return prefix


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


def estimate_plan_seconds(db: Session, plan: list[dict[str, Any]]) -> float:
    """What a plan costs in focused seconds, from the caller's own per-mode
    latency means — the same estimator the minutes budget uses, so a promised
    session length matches the session actually dealt."""
    seconds = _mode_seconds(db)
    return sum(seconds.get(item["mode"], FALLBACK_MODE_SECONDS) for item in plan)


def build_smart_plan_for_revisions(
    db: Session,
    revisions: list[models.PassageRevision],
    segment_kinds: list[str] | None,
    only_segment_ids: set[str] | None = None,
    minutes: int | None = None,
    cap: int | None = SMART_SESSION_CAP,
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
    review_states = list(
        db.scalars(
            select(models.ReviewState).where(
                models.ReviewState.segment_id.in_([segment.id for segment in all_segments])
            )
        )
    )
    stages = {state.segment_id: state.mastery_stage for state in review_states}
    acquisition_succeeded = {
        state.segment_id: state.acquisition_succeeded for state in review_states
    }
    line_numbers_by_revision = {
        revision.id: _line_number_map(_ordered_segments(revision, None))
        for revision, _segments in revision_segments
    }
    difficult_ids = _difficult_segment_ids(db)
    due_ids = due_segment_ids(db, [segment.id for segment in all_segments])
    revisions_with_reference = {
        revision.id
        for revision, _segments in revision_segments
        if _has_reference_audio(db, revision.id)
    }
    mode_counts: defaultdict[str, dict[str, int]] = defaultdict(dict)
    for segment_id, mode, count in db.execute(
        select(models.Attempt.segment_id, models.Attempt.mode, func.count(models.Attempt.id))
        .where(models.Attempt.segment_id.in_([segment.id for segment in all_segments]))
        .group_by(models.Attempt.segment_id, models.Attempt.mode)
    ):
        if segment_id is not None:
            mode_counts[segment_id][mode] = count
    last_ratings: dict[str, str] = {}
    last_modes: dict[str, str] = {}
    for segment_id, rating, mode in db.execute(
        select(models.Attempt.segment_id, models.Attempt.rating, models.Attempt.mode)
        .where(models.Attempt.segment_id.in_([segment.id for segment in all_segments]))
        .order_by(models.Attempt.created_at, models.Attempt.id)
    ):
        if segment_id is not None:
            last_ratings[segment_id] = rating
            last_modes[segment_id] = mode
    has_chain_context: dict[str, bool] = {}
    for revision, _segments in revision_segments:
        learned_prefix = _learned_prefix(_line_segments(revision.segments), stages)
        for index, line in enumerate(learned_prefix):
            has_chain_context[line.id] = index > 0
    modes = {
        segment.id: smart_mode_for(
            stages.get(segment.id),
            segment.id in difficult_ids,
            kind=segment.kind,
            mode_counts=mode_counts[segment.id],
            has_reference_audio=segment.revision_id in revisions_with_reference,
            has_translation=_translation_text(segment) is not None,
            acquisition_succeeded=acquisition_succeeded.get(segment.id, False),
            last_rating=last_ratings.get(segment.id),
            last_mode=last_modes.get(segment.id),
            has_chain_context=has_chain_context.get(segment.id, False),
        )
        for segment in all_segments
    }
    cue_spans_by_revision = {
        revision.id: _reference_cue_spans(db, revision.id)
        for revision, _segments in revision_segments
        if revision.id in revisions_with_reference
    }
    lines_by_ordinal_by_revision = {
        revision.id: {
            segment.ordinal: segment
            for segment in revision.segments
            if segment.kind == "line"
        }
        for revision, _segments in revision_segments
    }
    # Acquisition's encounter phase is now the single first-exposure surface;
    # reference audio remains available on that card, so a separate shadowing
    # item would split one deliberate lesson into two graded attempts.
    shadow_first: set[str] = set()
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
            _triage_rank(
                stages.get(entry[2].id),
                entry[2].id in difficult_ids,
                entry[2].id in due_ids,
            ),
            entry[0],
            entry[2].ordinal,
        ),
    )
    chosen: list[tuple[int, models.PassageRevision, models.Segment]] = []
    # Extra repetitions keyed by segment id, populated only by the minutes path
    # when one full pass leaves budget on the clock. fill_rotations[id][round]
    # is the mode to use for that segment's (round+1)-th extra turn.
    fill_reps: dict[str, int] = {}
    fill_rotations: dict[str, list[str]] = {}
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
        # Every targeted segment fit in one pass and time remains: spend the
        # leftover budget on varied repetitions so the chosen minutes are a
        # target, not just a ceiling. Reps are dealt highest-triage-first, so
        # weak links and learning material soak up the extra time before solid
        # lines do; the per-segment rotation cap keeps it from over-drilling.
        if chosen and len(chosen) == len(triaged):
            for entry in triaged:
                segment = entry[2]
                fill_rotations[entry[2].id] = [
                    mode
                    for mode in FILL_MODE_CYCLE
                    if mode != modes[segment.id]
                    and not (
                        segment.kind == "juncture"
                        and mode
                        in {
                            PracticeMode.forward_chaining.value,
                            PracticeMode.backward_chaining.value,
                            # Ordering a 3-word head is trivial; junctures skip
                            # word_bank in the fill rotation too.
                            PracticeMode.word_bank.value,
                        }
                    )
                ]
                fill_reps[segment.id] = 0
            progressed = True
            while progressed:
                progressed = False
                for entry in triaged:
                    segment = entry[2]
                    rotation = fill_rotations[segment.id]
                    count = fill_reps[segment.id]
                    if count >= len(rotation):
                        continue
                    cost = seconds.get(rotation[count], FALLBACK_MODE_SECONDS)
                    if budget - cost < 0:
                        continue
                    budget -= cost
                    fill_reps[segment.id] = count + 1
                    progressed = True
    else:
        # The cap limits ITEMS, not segments: a shadowed new segment takes
        # two slots, so a fresh passage with audio still ends while momentum
        # lasts. cap=None (the library-wide Today queue) takes everything —
        # a due queue must be clearable, and FSRS already bounds its size.
        used = 0
        for entry in triaged:
            segment = entry[2]
            weight = 2 if segment.id in shadow_first else 1
            if cap is not None and chosen and used + weight > cap:
                break
            used += weight
            chosen.append(entry)

    items: list[dict[str, Any]] = []

    def emit(target: models.Segment, mode: str, context: list[models.Segment]) -> None:
        # The revision snapshot on each item keeps full-passage grading scoped
        # correctly, so the target's own revision id rides along.
        line_numbers = (
            _line_numbers(context, line_numbers_by_revision[target.revision_id])
            if mode
            in {
                PracticeMode.forward_chaining.value,
                PracticeMode.backward_chaining.value,
            }
            else None
        )
        prompt = prompt_for(
            mode,
            target,
            context,
            personal_notes.get(target.id, target.cue),
            line_numbers,
        )
        _attach_juncture_audio_cue(
            prompt,
            mode,
            target,
            cue_spans_by_revision.get(target.revision_id, {}),
            lines_by_ordinal_by_revision.get(target.revision_id, {}),
        )
        items.append(
            {
                "revision_id": target.revision_id,
                "segment_id": target.id,
                "mode": mode,
                "prompt": prompt,
            }
        )

    def context_for(
        available: list[models.Segment],
        selected: list[models.Segment],
        target: models.Segment,
        mode: str,
    ) -> list[models.Segment]:
        if mode in {
            PracticeMode.forward_chaining.value,
            PracticeMode.backward_chaining.value,
        }:
            chain = _line_segments(available)
            learned_prefix = _learned_prefix(chain, stages)
            if target.id not in {segment.id for segment in learned_prefix}:
                return [target]
            target_index = next(
                position
                for position, segment in enumerate(learned_prefix)
                if segment.id == target.id
            )
            if mode == PracticeMode.forward_chaining.value:
                return learned_prefix[: target_index + 1]
            return learned_prefix[target_index:]
        target_index = next(
            position for position, segment in enumerate(selected) if segment.id == target.id
        )
        return selected[target_index:]

    # Present survivors in collection-member order and passage order.
    selected_by_revision: list[
        tuple[models.PassageRevision, list[models.Segment], list[models.Segment]]
    ] = []
    for revision, _available in revision_segments:
        # Chaining must remain a continuous passage exercise even when triage
        # or due-only filtering selected only a subset of targets.
        available = _ordered_segments(revision, segment_kinds)
        selected = sorted(
            (
                segment
                for _, chosen_revision, segment in chosen
                if chosen_revision.id == revision.id
            ),
            key=lambda segment: (segment.ordinal, segment.kind != "juncture"),
        )
        selected_by_revision.append((revision, available, selected))

    # Primary pass: each segment's stage-chosen mode, with a shadow lead-in on
    # first audio exposure.
    for _revision, available, selected in selected_by_revision:
        turns = _shuffle_random_start_turns(
            [(target, modes[target.id]) for target in selected]
        )
        for target, mode in turns:
            if target.id in shadow_first:
                emit(
                    target,
                    PracticeMode.shadowing.value,
                    context_for(
                        available,
                        selected,
                        target,
                        PracticeMode.shadowing.value,
                    ),
                )
            emit(target, mode, context_for(available, selected, target, mode))

    # Budget-fill repetitions, presented as further run-throughs of the passage
    # rather than one segment drilled back to back.
    for round_index in range(max(fill_reps.values(), default=0)):
        for _revision, available, selected in selected_by_revision:
            turns = _shuffle_random_start_turns(
                [
                    (target, fill_rotations[target.id][round_index])
                    for target in selected
                    if fill_reps.get(target.id, 0) > round_index
                ]
            )
            for target, mode in turns:
                emit(target, mode, context_for(available, selected, target, mode))

    # The holistic finisher closes the session, once every targeted segment of
    # a passage has graduated.
    for revision, _available, selected in selected_by_revision:
        if all_graduated[revision.id] and selected:
            emit(selected[0], PracticeMode.full_passage.value, selected)
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
    line_numbers_by_id = _line_number_map(_ordered_segments(revision, None))
    cue_spans = _reference_cue_spans(db, revision.id)
    lines_by_ordinal = {
        segment.ordinal: segment
        for segment in revision.segments
        if segment.kind == "line"
    }
    items: list[dict[str, Any]] = []
    for mode in modes:
        targets = segments
        if mode == PracticeMode.word_bank.value:
            # Ordering a short transition head is trivial rather than useful
            # retrieval practice. Keep junctures out of the bank in manual
            # plans as well as the smart and minutes-fill paths.
            targets = [segment for segment in segments if segment.kind != "juncture"]
        elif mode == PracticeMode.random_start.value:
            targets = _random_start_order(segments)
        elif mode == PracticeMode.weak_link.value:
            targets = [segment for segment in segments if segment.id in difficult_ids] or segments[
                :1
            ]
        elif mode == PracticeMode.meaning_recall.value:
            # Meaning needs a drafted translation to cue from; untranslated
            # lines (and junctures, which never carry one) are skipped.
            targets = [
                segment for segment in segments if _translation_text(segment) is not None
            ]
        elif mode in {PracticeMode.full_passage.value, PracticeMode.recital.value}:
            targets = segments[:1]
        for target in targets:
            target_index = next(
                position for position, segment in enumerate(segments) if segment.id == target.id
            )
            context = (
                segments[: target_index + 1]
                if mode == PracticeMode.forward_chaining.value
                else segments[target_index:]
            )
            line_numbers = (
                _line_numbers(context, line_numbers_by_id)
                if mode
                in {
                    PracticeMode.forward_chaining.value,
                    PracticeMode.backward_chaining.value,
                }
                else None
            )
            prompt = prompt_for(
                mode,
                target,
                context,
                personal_notes.get(target.id, target.cue),
                line_numbers,
            )
            _attach_juncture_audio_cue(prompt, mode, target, cue_spans, lines_by_ordinal)
            items.append(
                {
                    "revision_id": revision.id,
                    "segment_id": target.id,
                    "mode": mode,
                    "prompt": prompt,
                }
            )
    return items
