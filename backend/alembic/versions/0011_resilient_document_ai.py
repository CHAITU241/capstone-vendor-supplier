"""Track structured extraction and search indexing independently per document."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_resilient_document_ai"
down_revision: str | None = "0010_reviewer_workbench"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("ai_extraction_status", sa.String(20), nullable=False, server_default="pending"))
    op.add_column("documents", sa.Column("ai_extraction_error", sa.String(500), nullable=True))
    op.add_column("documents", sa.Column("ai_index_status", sa.String(20), nullable=False, server_default="pending"))
    op.add_column("documents", sa.Column("ai_index_error", sa.String(500), nullable=True))
    op.create_index("ix_documents_ai_extraction_status", "documents", ["ai_extraction_status"])
    op.create_index("ix_documents_ai_index_status", "documents", ["ai_index_status"])


def downgrade() -> None:
    op.drop_index("ix_documents_ai_index_status", table_name="documents")
    op.drop_index("ix_documents_ai_extraction_status", table_name="documents")
    op.drop_column("documents", "ai_index_error")
    op.drop_column("documents", "ai_index_status")
    op.drop_column("documents", "ai_extraction_error")
    op.drop_column("documents", "ai_extraction_status")
