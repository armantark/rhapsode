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


def review_segment(db: Session, segment_id: str, rating: str) -> models.ReviewState:
    state = db.scalar(select(models.ReviewState).where(models.ReviewState.segment_id == segment_id))
    card = Card.from_json(state.fsrs_card_json) if state else Card()
    scheduler = Scheduler(desired_retention=get_settings().desired_retention)
    card, _review_log = scheduler.review_card(card, RATING_MAP[rating], datetime.now(UTC))
    if state is None:
        state = models.ReviewState(
            segment_id=segment_id,
            fsrs_card_json=card.to_json(),
            due_at=card.due,
            mastery_stage="new",
            clean_count=0,
            attempt_count=0,
        )
        db.add(state)
    state.fsrs_card_json = card.to_json()
    state.due_at = card.due
    state.attempt_count += 1
    state.clean_count = _next_clean_streak(state.clean_count, rating)
    state.mastery_stage = mastery_stage(state)
    return state


DURABLE_STREAK = 5
REVIEW_STREAK = 2


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
    if state.clean_count >= DURABLE_STREAK:
        return "durable"
    if state.clean_count >= REVIEW_STREAK:
        return "review"
    if state.attempt_count:
        return "learning"
    return "new"
