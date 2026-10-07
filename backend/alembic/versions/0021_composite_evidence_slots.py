"""Add upload types for policy requirements containing multiple physical files."""

from collections.abc import Sequence

from alembic import op

revision: str = "0021_composite_slots"
down_revision: str | None = "0020_trans_declaration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ADDED_TYPES = (
    "BASE_002_DECLARATION",
    "SITE_002_TRAINING",
    "FOOD_002_PLAN",
    "PROD_001_WARRANTY",
    "TRAIN_001_OUTLINE",
    "TRAIN_001_CREDENTIAL",
)


def upgrade() -> None:
    # SQLAlchemy persists Python enum member names in PostgreSQL.
    with op.get_context().autocommit_block():
        for value in ADDED_TYPES:
            op.execute(f"ALTER TYPE document_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL cannot remove individual enum values without recreating the type.
    pass
