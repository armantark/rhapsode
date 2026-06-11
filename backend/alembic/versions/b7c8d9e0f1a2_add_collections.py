"""add_collections

Revision ID: b7c8d9e0f1a2
Revises: a1f2c3d4e5f6
Create Date: 2026-06-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "a1f2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "collection_passages",
        sa.Column("collection_id", sa.String(), nullable=False),
        sa.Column("passage_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["passage_id"], ["passages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("collection_id", "passage_id"),
        sa.UniqueConstraint("collection_id", "position"),
    )
    with op.batch_alter_table("practice_sessions") as batch_op:
        batch_op.alter_column("revision_id", existing_type=sa.String(), nullable=True)
        batch_op.add_column(sa.Column("collection_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_practice_sessions_collection_id",
            "collections",
            ["collection_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("practice_items") as batch_op:
        batch_op.add_column(sa.Column("revision_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_practice_items_revision_id",
            "passage_revisions",
            ["revision_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.execute(
        """
        UPDATE practice_items
        SET revision_id = (
            SELECT practice_sessions.revision_id
            FROM practice_sessions
            WHERE practice_sessions.id = practice_items.session_id
        )
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("practice_items") as batch_op:
        batch_op.drop_constraint("fk_practice_items_revision_id", type_="foreignkey")
        batch_op.drop_column("revision_id")
    op.execute("DELETE FROM practice_sessions WHERE revision_id IS NULL")
    with op.batch_alter_table("practice_sessions") as batch_op:
        batch_op.drop_constraint("fk_practice_sessions_collection_id", type_="foreignkey")
        batch_op.drop_column("collection_id")
        batch_op.alter_column("revision_id", existing_type=sa.String(), nullable=False)
    op.drop_table("collection_passages")
    op.drop_table("collections")
