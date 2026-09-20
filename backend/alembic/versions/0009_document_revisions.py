"""Retain originals and metadata when an upload is removed or replaced."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_document_revisions"
down_revision: str | None = "0008_synthetic_policy_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("sha256", sa.String(64), nullable=True))
    op.add_column("documents", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.create_table(
        "document_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("supplier_id", sa.Uuid(), sa.ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_type", sa.String(40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_document_revisions_supplier_id", "document_revisions", ["supplier_id"])


def downgrade() -> None:
    op.drop_index("ix_document_revisions_supplier_id", table_name="document_revisions")
    op.drop_table("document_revisions")
    op.drop_column("documents", "revision")
    op.drop_column("documents", "sha256")
