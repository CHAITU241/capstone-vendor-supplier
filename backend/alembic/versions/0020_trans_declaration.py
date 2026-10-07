"""Split TRANS-001 into insurance and custody-declaration upload slots."""

from collections.abc import Sequence

from alembic import op

revision: str = "0020_trans_declaration"
down_revision: str | None = "0019_addl_evidence_extract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLAlchemy persists Python enum member names in PostgreSQL.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE document_type ADD VALUE IF NOT EXISTS "
            "'TRANS_001_DECLARATION'"
        )


def downgrade() -> None:
    # PostgreSQL cannot remove one enum value without recreating the type.
    pass
