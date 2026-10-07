"""Persist AI extraction from reviewer-verified additional evidence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_addl_evidence_extract"
down_revision: str | None = "0018_other_supplier_path"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "additional_documents",
        sa.Column("erp_fields", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "additional_documents",
        sa.Column("ai_extraction_status", sa.String(20), nullable=False, server_default="pending"),
    )
    op.add_column(
        "additional_documents",
        sa.Column("ai_extraction_error", sa.String(500), nullable=True),
    )
    op.add_column(
        "additional_documents",
        sa.Column("text_extraction_method", sa.String(20), nullable=True),
    )
    op.add_column(
        "additional_documents",
        sa.Column("ocr_quality_score", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("additional_documents", "ocr_quality_score")
    op.drop_column("additional_documents", "text_extraction_method")
    op.drop_column("additional_documents", "ai_extraction_error")
    op.drop_column("additional_documents", "ai_extraction_status")
    op.drop_column("additional_documents", "erp_fields")
