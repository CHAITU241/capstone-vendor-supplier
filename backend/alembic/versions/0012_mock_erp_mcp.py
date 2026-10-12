"""Add persistent mock ERP records and MCP tool attempt audit."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_mock_erp_mcp"
down_revision: str | None = "0011_resilient_document_ai"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "erp_supplier_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("erp_supplier_id", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("source_supplier_id", sa.Uuid(), nullable=False),
        sa.Column("legal_name", sa.String(200), nullable=False),
        sa.Column("tax_reference", sa.String(100), nullable=False),
        sa.Column("bank_account_number", sa.String(100), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("subcategory", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("erp_supplier_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    for column in ("erp_supplier_id", "idempotency_key", "source_supplier_id", "legal_name", "tax_reference", "bank_account_number", "status"):
        op.create_index(f"ix_erp_supplier_records_{column}", "erp_supplier_records", [column])
    op.create_table(
        "erp_tool_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(60), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("request_summary", sa.JSON(), nullable=False),
        sa.Column("response_summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("supplier_id", "operation", "status"):
        op.create_index(f"ix_erp_tool_attempts_{column}", "erp_tool_attempts", [column])


def downgrade() -> None:
    op.drop_table("erp_tool_attempts")
    op.drop_table("erp_supplier_records")
