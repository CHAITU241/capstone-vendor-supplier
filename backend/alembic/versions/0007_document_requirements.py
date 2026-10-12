"""Freeze the selected checklist when a supplier submits an application."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_document_requirements"
down_revision: str | None = "0006_supplier_portal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("suppliers", sa.Column("requirements_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("suppliers", "requirements_snapshot")
