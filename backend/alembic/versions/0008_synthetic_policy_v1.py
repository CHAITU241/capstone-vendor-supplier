"""Add policy evidence types and the payment/tax portal reference fields."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_synthetic_policy_v1"
down_revision: str | None = "0007_document_requirements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ADDED_TYPES = (
    "BANK", "CONF_001", "SEC_001", "PRIV_001", "CONT_001", "INS_CYB_001",
    "INS_PI_001", "CRED_001", "PEOP_001", "PEOP_002", "SITE_001", "SITE_002",
    "FOOD_001", "FOOD_002", "EVENT_001", "TRANS_001", "STORE_001",
    "PROD_001", "PAY_001", "TRAIN_001",
)


def upgrade() -> None:
    # PostgreSQL enum values are the SQLAlchemy member names, not their Python values.
    with op.get_context().autocommit_block():
        for value in ADDED_TYPES:
            op.execute(f"ALTER TYPE document_type ADD VALUE IF NOT EXISTS '{value}'")
    op.add_column("suppliers", sa.Column("tax_reference", sa.String(100)))
    op.add_column("suppliers", sa.Column("bank_account_number", sa.String(100)))
    op.add_column("suppliers", sa.Column("bank_ifsc", sa.String(20)))


def downgrade() -> None:
    op.drop_column("suppliers", "bank_ifsc")
    op.drop_column("suppliers", "bank_account_number")
    op.drop_column("suppliers", "tax_reference")
    # PostgreSQL cannot drop individual enum values without recreating the type.
    # Keeping the values lets existing documents remain readable after downgrade.
