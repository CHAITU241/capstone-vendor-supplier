"""Persist human evidence review, field review, and the mock ERP payload."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_reviewer_workbench"
down_revision: str | None = "0009_document_revisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("suppliers", sa.Column("erp_payload", sa.JSON(), nullable=True))
    for table in ("documents", "extracted_fields"):
        op.add_column(table, sa.Column("review_status", sa.String(20), nullable=False, server_default="pending"))
        op.add_column(table, sa.Column("review_comment", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("reviewed_by", sa.String(100), nullable=True))
        op.add_column(table, sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for table in ("extracted_fields", "documents"):
        op.drop_column(table, "reviewed_at")
        op.drop_column(table, "reviewed_by")
        op.drop_column(table, "review_comment")
        op.drop_column(table, "review_status")
    op.drop_column("suppliers", "erp_payload")
