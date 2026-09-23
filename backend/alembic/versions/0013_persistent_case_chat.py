"""Persist audience-separated supplier case conversations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_persistent_case_chat"
down_revision: str | None = "0012_mock_erp_mcp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("audience", sa.String(20), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "supplier_id", "audience", "sequence",
            name="uq_assistant_messages_supplier_audience_sequence",
        ),
    )
    op.create_index("ix_assistant_messages_supplier_id", "assistant_messages", ["supplier_id"])
    op.create_index("ix_assistant_messages_audience", "assistant_messages", ["audience"])


def downgrade() -> None:
    op.drop_table("assistant_messages")
