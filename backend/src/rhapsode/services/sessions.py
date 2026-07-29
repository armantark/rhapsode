from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from rhapsode import models
from rhapsode.config import get_settings
from rhapsode.services import planning
from rhapsode.services.scheduling import FAILURE_RATINGS

# Cards that grade several review units from one recitation. recital is absent
# on purpose: its stumble map already attributes per line.
CHAINED_RECALL_MODES = {"forward_chaining", "backward_chaining", "full_passage"}


def attribute_chain_failure(
    mode: str, rating: str, affected: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Blame a failed multi-line recall on its last line.

    Reaching the end of a chain means the earlier lines were recited to get
    there, so the line that gave out is the last one. Fanning the failing grade
    across the whole chain would bury already-solid lines under lapses they did
    not earn; the earlier lines grade "hesitant" instead, which records the
    recall as real but effortful. Successes still fan unchanged.
    """
    if mode not in CHAINED_RECALL_MODES or rating not in FAILURE_RATINGS:
        return affected
    return [(segment_id, "hesitant") for segment_id, _ in affected[:-1]] + affected[-1:]


def expire_stale_sessions(db: Session, now: datetime | None = None) -> int:
    """Close abandoned sessions after their resumability window.

    Practice sessions are restart-safe, but an unfinished card from days ago is
    no longer the same focused practice event. Expiry preserves its attempts and
    plan for history while keeping it out of the active queue.
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(hours=get_settings().session_expiry_hours)
    stale = list(
        db.scalars(
            select(models.PracticeSession)
            .where(models.PracticeSession.status == "active")
            .where(models.PracticeSession.updated_at < cutoff)
        )
    )
    for session in stale:
        session.status = "expired"
    if stale:
        db.commit()
    return len(stale)


def refresh_dealt_prompt(db: Session, session: models.PracticeSession) -> None:
    """Materialize stateful prompts only when their card reaches the learner.

    A three-card runway block intentionally changes the ladder after each
    success. Persisting all three prompts when the session is planned would
    freeze them at the same cue level.
    """
    item = next((candidate for candidate in session.items if not candidate.completed), None)
    if item is None or item.segment_id is None:
        return
    is_guided = item.mode == "guided_recall"
    is_acquisition_retry = item.mode == "acquisition" and item.retry_source_item_id is not None
    if not is_guided and not is_acquisition_retry:
        return
    target = db.get(models.Segment, item.segment_id)
    if target is None:
        return
    state = db.scalar(
        select(models.ReviewState).where(models.ReviewState.segment_id == target.id)
    )
    note = db.get(models.PersonalNote, target.id)
    prompt = planning.prompt_for(
        item.mode,
        target,
        [target],
        note.text if note is not None else target.cue,
        learning_step=state.learning_step if state and state.learning_step is not None else 0,
        learning_success_count=state.learning_success_count if state else 0,
    )
    # The randomized response modality and word-bank order belong to the card,
    # not to each HTTP read. Only the mastery-dependent support is refreshed.
    for stable_field in ("response_format", "word_bank"):
        if stable_field in item.prompt:
            prompt[stable_field] = item.prompt[stable_field]
    item.prompt = prompt
