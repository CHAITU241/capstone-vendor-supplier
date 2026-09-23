"""Record OCR provenance for uploaded evidence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_document_ocr"
down_revision: str | None = "0013_persistent_case_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("text_extraction_method", sa.String(20), nullable=True))
    op.add_column("documents", sa.Column("ocr_pages", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("documents", sa.Column("ocr_language", sa.String(50), nullable=True))
    op.add_column("documents", sa.Column("ocr_warnings", sa.JSON(), nullable=False, server_default="[]"))
    op.execute("UPDATE documents SET text_extraction_method = 'native' WHERE extracted_text IS NOT NULL")


def downgrade() -> None:
    op.drop_column("documents", "ocr_warnings")
    op.drop_column("documents", "ocr_language")
    op.drop_column("documents", "ocr_pages")
    op.drop_column("documents", "text_extraction_method")
