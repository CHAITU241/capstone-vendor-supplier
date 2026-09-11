"""Add Phase 3 compliance results and supplier decisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_phase_three_compliance"
down_revision: str | None = "0004_phase_two_ai_rag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    compliance_status = sa.Enum(
        "PASS",
        "FAIL",
        "NEEDS_REVIEW",
        name="compliance_status",
    )

    op.add_column("suppliers", sa.Column("decision_reason", sa.Text(), nullable=True))
    op.add_column(
        "suppliers",
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "suppliers",
        sa.Column("erp_supplier_id", sa.String(length=100), nullable=True),
    )

    op.create_table(
        "compliance_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("rule_code", sa.String(length=100), nullable=False),
        sa.Column("status", compliance_status, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"], ["suppliers.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "supplier_id",
            "rule_code",
            name="uq_compliance_results_supplier_rule",
        ),
    )
    op.create_index(
        "ix_compliance_results_supplier_id",
        "compliance_results",
        ["supplier_id"],
    )
    op.create_index(
        "ix_compliance_results_rule_code",
        "compliance_results",
        ["rule_code"],
    )
    op.create_index(
        "ix_compliance_results_status",
        "compliance_results",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("compliance_results")
    op.drop_column("suppliers", "erp_supplier_id")
    op.drop_column("suppliers", "decided_at")
    op.drop_column("suppliers", "decision_reason")
    op.execute("DROP TYPE IF EXISTS compliance_status")
