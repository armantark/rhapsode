"""Fit personal FSRS parameters from the accumulated review log.

Why this is a script and not an endpoint: the py-fsrs optimizer pulls torch
and pandas, which have no business inside the practice loop or the PyInstaller
sidecar. Run it occasionally (it needs the `optimizer` extra):

    uv run --extra optimizer python scripts/optimize_fsrs.py

It reads every persisted review log, refuses to fit on thin data, writes the
fitted parameters to the `fsrs_parameters` app setting (which the scheduler
reads on every review, falling back to defaults when absent), and prints the
measured recall rate so the fit can be sanity-checked against the 0.9 target.
Pass --dry-run to see everything without writing.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from rhapsode import migrations, models
from rhapsode.database import SessionLocal
from rhapsode.services.scheduling import FSRS_PARAMETERS_KEY

# Below this many reviews the fit chases noise; py-fsrs guidance is a few
# hundred at minimum. Defaults are better than a bad fit.
MIN_REVIEWS = 400


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="fit but do not persist")
    parser.add_argument(
        "--min-reviews",
        type=int,
        default=MIN_REVIEWS,
        help="refuse to fit below this many logged reviews",
    )
    args = parser.parse_args()

    try:
        from fsrs import Optimizer, Rating, ReviewLog
    except ImportError:
        print("The optimizer extra is missing. Run with: uv run --extra optimizer ...")
        return 2

    migrations.main()
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(models.FsrsReviewLog).order_by(models.FsrsReviewLog.reviewed_at)
            )
        )
        if len(rows) < args.min_reviews:
            print(
                f"Only {len(rows)} logged reviews; need {args.min_reviews} for a stable "
                "fit. Keep practicing — defaults remain in effect."
            )
            return 1

        review_logs = [
            ReviewLog(
                card_id=row.card_id,
                rating=Rating(row.rating),
                review_datetime=row.reviewed_at,
                review_duration=row.review_duration_ms,
            )
            for row in rows
        ]
        again = sum(1 for row in rows if row.rating == int(Rating.Again))
        measured = (len(rows) - again) / len(rows)
        print(f"Reviews: {len(rows)} · measured recall rate: {measured:.3f}")

        optimizer = Optimizer(review_logs)
        parameters = [float(value) for value in optimizer.compute_optimal_parameters()]
        print(f"Fitted parameters: {parameters}")

        if args.dry_run:
            print("Dry run — nothing written.")
            return 0

        setting = db.get(models.AppSetting, FSRS_PARAMETERS_KEY)
        if setting is None:
            db.add(models.AppSetting(key=FSRS_PARAMETERS_KEY, value=parameters))
        else:
            setting.value = parameters
        db.commit()
        print(f"Wrote {FSRS_PARAMETERS_KEY}; the scheduler uses them from the next review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
