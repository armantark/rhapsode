"""add_gated_learning_ladder

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-21 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "review_states",
        sa.Column("learning_step", sa.Integer(), nullable=True, server_default="0"),
    )
    op.add_column(
        "review_states",
        sa.Column(
            "learning_success_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    # Material already in review/durable has graduated from line acquisition.
    # Active new/learning material receives the improved ladder in place.
    op.execute(
        "UPDATE review_states SET learning_step = NULL "
        "WHERE mastery_stage IN ('review', 'durable')"
    )


def downgrade() -> None:
    op.drop_column("review_states", "learning_success_count")
    op.drop_column("review_states", "learning_step")
