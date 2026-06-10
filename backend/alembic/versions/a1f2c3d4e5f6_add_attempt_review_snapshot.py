"""add_attempt_review_snapshot

Revision ID: a1f2c3d4e5f6
Revises: 60085f3c84a1
Create Date: 2026-06-10 14:55:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1f2c3d4e5f6"
down_revision: str | None = "60085f3c84a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("attempts", sa.Column("review_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("attempts", "review_snapshot")
