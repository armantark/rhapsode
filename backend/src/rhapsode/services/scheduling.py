from datetime import UTC, datetime
from typing import Any

from fsrs import Card, Rating, Scheduler
from sqlalchemy import select
from sqlalchemy.orm import Session

from rhapsode import models
from rhapsode.config import get_settings

# "incorrect" (the Hard button, "errors in recall") schedules as a LAPSE: FSRS
# treats Rating.Hard as a successful recall, which would grow the interval on
# exactly the lines that were just recited wrong. The ladder and analytics keep
# the revealed/incorrect distinction (grill B2); only the schedule unifies them.
RATING_MAP = {
    "clean": Rating.Easy,
    "hesitant": Rating.Good,
    "incorrect": Rating.Again,
    "revealed": Rating.Again,
}

FAILURE_RATINGS = {"incorrect", "revealed"}


def snapshot_review_state(db: Session, segment_id: str) -> dict[str, Any]:
    """Capture a segment's review state before an attempt mutates it, so the
    attempt can be undone exactly. ``existed: False`` means there was no state
    yet and undo should delete the one the attempt created."""
    state = db.scalar(
        select(models.ReviewState).where(models.ReviewState.segment_id == segment_id)
    )
    if state is None:
        return {"segment_id": segment_id, "existed": False}
    return {
        "segment_id": segment_id,
        "existed": True,
        "fsrs_card_json": state.fsrs_card_json,
        "due_at": state.due_at.isoformat(),
        "mastery_stage": state.mastery_stage,
        "clean_count": state.clean_count,
        "attempt_count": state.attempt_count,
        "acquisition_succeeded": state.acquisition_succeeded,
        "learning_step": state.learning_step,
        "learning_success_count": state.learning_success_count,
    }


def restore_review_state(db: Session, snapshot: dict[str, Any]) -> None:
    """Inverse of an attempt's effect on one segment's review state."""
    state = db.scalar(
        select(models.ReviewState).where(
            models.ReviewState.segment_id == snapshot["segment_id"]
        )
    )
    if not snapshot.get("existed"):
        if state is not None:
            db.delete(state)
        return
    if state is None:
        state = models.ReviewState(segment_id=snapshot["segment_id"])
        db.add(state)
    state.fsrs_card_json = snapshot["fsrs_card_json"]
    state.due_at = datetime.fromisoformat(snapshot["due_at"])
    state.mastery_stage = snapshot["mastery_stage"]
    state.clean_count = snapshot["clean_count"]
    state.attempt_count = snapshot["attempt_count"]
    # Snapshots written before this field existed belong to review rows that
    # the migration marks acquired.
    state.acquisition_succeeded = snapshot.get("acquisition_succeeded", True)
    state.learning_step = snapshot.get("learning_step")
    state.learning_success_count = snapshot.get("learning_success_count", 0)


# Setting key holding personally fitted FSRS weights, written by
# scripts/optimize_fsrs.py once enough review history exists. Absent or
# malformed → py-fsrs population defaults, so the fit is strictly opt-in.
FSRS_PARAMETERS_KEY = "fsrs_parameters"


def _fsrs_parameters(db: Session) -> list[float] | None:
    setting = db.get(models.AppSetting, FSRS_PARAMETERS_KEY)
    if setting is None or not isinstance(setting.value, list) or not setting.value:
        return None
    try:
        return [float(value) for value in setting.value]
    except (TypeError, ValueError):
        return None


def _scheduler(db: Session) -> Scheduler:
    parameters = _fsrs_parameters(db)
    desired_retention = get_settings().desired_retention
    if parameters is None:
        return Scheduler(desired_retention=desired_retention)
    try:
        return Scheduler(parameters=parameters, desired_retention=desired_retention)
    except ValueError:
        # A stored parameter list from an incompatible py-fsrs version must
        # not break grading; population defaults are always valid.
        return Scheduler(desired_retention=desired_retention)


def review_segment(
    db: Session,
    segment_id: str,
    rating: str,
    attempt_id: str | None = None,
    review_duration_ms: int | None = None,
    mode: str | None = None,
) -> models.ReviewState:
    state = db.scalar(select(models.ReviewState).where(models.ReviewState.segment_id == segment_id))
    card = Card.from_json(state.fsrs_card_json) if state else Card()
    scheduler = _scheduler(db)
    card, review_log = scheduler.review_card(card, RATING_MAP[rating], datetime.now(UTC))
    if attempt_id is not None:
        # The optimizer's raw material. Keyed to the attempt so undo retracts
        # the log along with the review it snapshots.
        db.add(
            models.FsrsReviewLog(
                attempt_id=attempt_id,
                segment_id=segment_id,
                card_id=review_log.card_id,
                rating=int(review_log.rating),
                reviewed_at=review_log.review_datetime,
                review_duration_ms=review_duration_ms,
            )
        )
    if state is None:
        segment = db.get(models.Segment, segment_id)
        state = models.ReviewState(
            segment_id=segment_id,
            fsrs_card_json=card.to_json(),
            due_at=card.due,
            mastery_stage="new",
            clean_count=0,
            attempt_count=0,
            acquisition_succeeded=False,
            learning_step=0 if segment is not None and segment.kind != "juncture" else None,
            learning_success_count=0,
        )
        db.add(state)
    state.fsrs_card_json = card.to_json()
    state.due_at = card.due
    state.attempt_count += 1
    state.clean_count = _next_clean_streak(state.clean_count, rating)
    if rating in {"hesitant", "clean"}:
        state.acquisition_succeeded = True
        if mode == "guided_recall" and state.learning_step is not None:
            # A clean recall is worth two of the phase's required recalls and a
            # hesitant one is worth one: recalling without hesitation says the
            # current support level is already surplus, so making it take the
            # same number of cards as a shaky recall just grinds. Overshooting
            # the requirement is fine — every threshold below compares with >=.
            state.learning_success_count += 2 if rating == "clean" else 1
            if state.learning_success_count >= LEARNING_STEP_SUCCESSES:
                from rhapsode.services.planning import (
                    learning_scaffold_steps,
                    learning_step_successes_required,
                )

                segment = db.get(models.Segment, segment_id)
                step_count = len(learning_scaffold_steps(segment)) if segment else 0
                required = (
                    learning_step_successes_required(segment, state.learning_step)
                    if segment
                    else LEARNING_STEP_SUCCESSES
                )
                if state.learning_success_count >= required:
                    state.learning_step = (
                        state.learning_step + 1
                        if state.learning_step + 1 < step_count
                        else None
                    )
                    state.learning_success_count = 0
    elif _previous_attempt_rating(db, segment_id, attempt_id) in FAILURE_RATINGS:
        _demote_learning_support(db, state, segment_id)
    state.mastery_stage = mastery_stage(state)
    return state


def _previous_attempt_rating(
    db: Session, segment_id: str, attempt_id: str | None
) -> str | None:
    """The rating of the attempt before the one being graded. The caller has
    already flushed the current attempt, so it must be excluded by id."""
    query = (
        select(models.Attempt.rating)
        .where(models.Attempt.segment_id == segment_id)
        .order_by(models.Attempt.created_at.desc(), models.Attempt.id.desc())
        .limit(1)
    )
    if attempt_id is not None:
        query = query.where(models.Attempt.id != attempt_id)
    return db.scalar(query)


def _demote_learning_support(
    db: Session, state: models.ReviewState, segment_id: str
) -> None:
    """Two consecutive failures say the current support level is too thin, so
    the line drops back a ladder phase instead of grinding at a phase it has
    not earned. A mastered line re-enters at the ladder's LAST phase: it needs
    the lightest scaffold back, not the whole ladder again. At step 0 nothing
    moves — acquisition support already re-engages there — and junctures have
    no ladder to fall down."""
    segment = db.get(models.Segment, segment_id)
    if segment is None or segment.kind == "juncture":
        return
    if state.learning_step is None:
        if not state.acquisition_succeeded:
            return
        from rhapsode.services.planning import learning_scaffold_steps

        step_count = len(learning_scaffold_steps(segment))
        if step_count == 0:
            return
        state.learning_step = step_count - 1
    elif state.learning_step > 0:
        state.learning_step -= 1
    else:
        return
    state.learning_success_count = 0


DURABLE_STREAK = 5
REVIEW_STREAK = 2
LEARNING_STEP_SUCCESSES = 3


def _next_clean_streak(streak: int, rating: str) -> int:
    """clean_count holds CONSECUTIVE cleans, not lifetime cleans (grill B2):
    stages must be able to regress so a lapsed line gets scaffolding back.
    Again wipes the streak; Hard demotes one threshold step (durable→review,
    review→learning); Good neither advances nor punishes."""
    match rating:
        case "clean":
            return streak + 1
        case "revealed":
            return 0
        case "incorrect":
            return REVIEW_STREAK if streak >= DURABLE_STREAK else 0
        case _:
            return streak


def mastery_stage(state: models.ReviewState) -> str:
    if not state.acquisition_succeeded:
        return "new"
    if state.learning_step is not None:
        return "learning"
    if state.clean_count >= DURABLE_STREAK:
        return "durable"
    if state.clean_count >= REVIEW_STREAK:
        return "review"
    if state.attempt_count:
        return "learning"
    return "new"
