"""Persist OCR extraction-reliability evidence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_ocr_quality"
down_revision: str | None = "0015_upload_validation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("ocr_quality_score", sa.Float(), nullable=True))
    op.add_column("documents", sa.Column("ocr_quality_status", sa.String(20), nullable=True))
    op.add_column("documents", sa.Column("ocr_quality_details", sa.JSON(), nullable=True))
    op.create_index(
        op.f("ix_documents_ocr_quality_status"),
        "documents",
        ["ocr_quality_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_documents_ocr_quality_status"), table_name="documents")
    op.drop_column("documents", "ocr_quality_details")
    op.drop_column("documents", "ocr_quality_status")
    op.drop_column("documents", "ocr_quality_score")
