"""add_media_cue_points

Revision ID: 60085f3c84a1
Revises: 9306b49e8942
Create Date: 2026-06-10 09:58:01.221456
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "60085f3c84a1"
down_revision: str | None = "9306b49e8942"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "media_assets",
        sa.Column("cue_points", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("media_assets", "cue_points")
