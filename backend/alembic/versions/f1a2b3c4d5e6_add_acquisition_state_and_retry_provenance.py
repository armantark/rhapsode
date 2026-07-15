"""add_acquisition_state_and_retry_provenance

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-07-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e0f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every pre-existing review state represents material already encountered
    # under the old ladder, so preserve it as acquired rather than forcing the
    # learner back through the new first lesson.
    op.add_column(
        "review_states",
        sa.Column(
            "acquisition_succeeded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    with op.batch_alter_table("practice_items") as batch_op:
        batch_op.add_column(sa.Column("retry_source_item_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_practice_items_retry_source_item_id",
            "practice_items",
            ["retry_source_item_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint(
            "uq_practice_items_retry_source_item_id", ["retry_source_item_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("practice_items") as batch_op:
        batch_op.drop_constraint(
            "uq_practice_items_retry_source_item_id", type_="unique"
        )
        batch_op.drop_constraint(
            "fk_practice_items_retry_source_item_id", type_="foreignkey"
        )
        batch_op.drop_column("retry_source_item_id")
    op.drop_column("review_states", "acquisition_succeeded")
