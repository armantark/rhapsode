from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from rhapsode import models
from rhapsode.config import get_settings


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
