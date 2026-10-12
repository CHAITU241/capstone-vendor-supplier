"""Add the controlled Other supplier review path."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_other_supplier_path"
down_revision: str | None = "0017_erp_identifier_separation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("suppliers", sa.Column("service_description", sa.Text(), nullable=True))
    op.add_column("suppliers", sa.Column("other_review_note", sa.Text(), nullable=True))
    op.add_column("suppliers", sa.Column("other_reviewed_by", sa.String(100), nullable=True))
    op.add_column(
        "suppliers",
        sa.Column("other_review_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "additional_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("uploaded_by", sa.String(100), nullable=False),
        sa.Column("verification_note", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_additional_documents_supplier_id"),
        "additional_documents",
        ["supplier_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_additional_documents_supplier_id"), table_name="additional_documents")
    op.drop_table("additional_documents")
    op.drop_column("suppliers", "other_review_completed_at")
    op.drop_column("suppliers", "other_reviewed_by")
    op.drop_column("suppliers", "other_review_note")
    op.drop_column("suppliers", "service_description")
