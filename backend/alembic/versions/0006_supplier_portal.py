"""Add supplier accounts, resumable applications and demo sessions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_supplier_portal"
down_revision: str | None = "0005_phase_three_compliance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portal_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_portal_accounts_email", "portal_accounts", ["email"], unique=True)
    op.create_table(
        "portal_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("portal_accounts.id", ondelete="CASCADE")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_portal_sessions_token_hash", "portal_sessions", ["token_hash"], unique=True)
    op.add_column("suppliers", sa.Column("category", sa.String(100)))
    op.add_column("suppliers", sa.Column("subcategory", sa.String(100)))
    op.add_column("suppliers", sa.Column("account_id", sa.Uuid(), sa.ForeignKey("portal_accounts.id")))
    op.create_unique_constraint("uq_suppliers_account_id", "suppliers", ["account_id"])
    op.add_column("suppliers", sa.Column("submitted_at", sa.DateTime(timezone=True)))
    # Existing cases remain visible to reviewers. New self-service cases start as drafts.
    op.execute("UPDATE suppliers SET submitted_at = NOW()")


def downgrade() -> None:
    op.drop_column("suppliers", "submitted_at")
    op.drop_constraint("uq_suppliers_account_id", "suppliers", type_="unique")
    op.drop_column("suppliers", "account_id")
    op.drop_column("suppliers", "subcategory")
    op.drop_column("suppliers", "category")
    op.drop_index("ix_portal_sessions_token_hash", table_name="portal_sessions")
    op.drop_table("portal_sessions")
    op.drop_index("ix_portal_accounts_email", table_name="portal_accounts")
    op.drop_table("portal_accounts")
