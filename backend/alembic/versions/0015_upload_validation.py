"""Persist pre-acceptance document validation evidence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_upload_validation"
down_revision: str | None = "0014_document_ocr"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("upload_validation_status", sa.String(20), nullable=False, server_default="pending"),
    )
    op.add_column("documents", sa.Column("upload_validation_details", sa.JSON(), nullable=True))
    op.create_index(
        op.f("ix_documents_upload_validation_status"),
        "documents",
        ["upload_validation_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_documents_upload_validation_status"), table_name="documents")
    op.drop_column("documents", "upload_validation_details")
    op.drop_column("documents", "upload_validation_status")
