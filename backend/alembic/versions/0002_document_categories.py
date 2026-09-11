"""Add document categories and enforce one document per category."""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_document_categories"
down_revision: str | None = "0001_phase_one"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLAlchemy stores the Python enum member names in PostgreSQL.
    op.execute("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'INCORPORATION'")
    op.execute("ALTER TYPE document_type ADD VALUE IF NOT EXISTS 'BANK'")
    op.create_unique_constraint(
        "uq_documents_supplier_document_type",
        "documents",
        ["supplier_id", "document_type"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_documents_supplier_document_type",
        "documents",
        type_="unique",
    )
    # PostgreSQL enum values are intentionally retained because removing them
    # requires rebuilding the type and can invalidate existing rows.
