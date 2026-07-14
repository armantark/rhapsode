"""add_source_reference_labels

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-07-13 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e0f1a2b3c4d5"
down_revision: str | None = "d9e0f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("passage_revisions", sa.Column("reference_label", sa.String(), nullable=True))
    op.add_column("segments", sa.Column("reference_label", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("segments", "reference_label")
    op.drop_column("passage_revisions", "reference_label")
