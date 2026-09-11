"""Add Phase 2 AI run and extracted field records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_phase_two_ai_rag"
down_revision: str | None = "0003_restore_three_types"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ai_run_type = sa.Enum("PROCESSING", "QUESTION", name="ai_run_type")
    ai_run_status = sa.Enum(
        "PROCESSING", "SUCCEEDED", "FAILED", name="ai_run_status"
    )

    op.add_column("documents", sa.Column("redacted_text", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("redaction_summary", sa.JSON(), nullable=True))

    op.create_table(
        "extracted_fields",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("field_name", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "supplier_id",
            "document_id",
            "field_name",
            name="uq_extracted_fields_supplier_document_name",
        ),
    )
    op.create_index("ix_extracted_fields_supplier_id", "extracted_fields", ["supplier_id"])
    op.create_index("ix_extracted_fields_document_id", "extracted_fields", ["document_id"])
    op.create_index("ix_extracted_fields_field_name", "extracted_fields", ["field_name"])

    op.create_table(
        "ai_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("run_type", ai_run_type, nullable=False),
        sa.Column("status", ai_run_status, nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("retrieval_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_runs_supplier_id", "ai_runs", ["supplier_id"])
    op.create_index("ix_ai_runs_run_type", "ai_runs", ["run_type"])
    op.create_index("ix_ai_runs_status", "ai_runs", ["status"])


def downgrade() -> None:
    op.drop_table("ai_runs")
    op.drop_table("extracted_fields")
    op.drop_column("documents", "redaction_summary")
    op.drop_column("documents", "redacted_text")
    op.execute("DROP TYPE IF EXISTS ai_run_status")
    op.execute("DROP TYPE IF EXISTS ai_run_type")
