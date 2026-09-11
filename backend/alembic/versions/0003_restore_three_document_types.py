"""Restore the original three supported document categories."""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_restore_three_types"
down_revision: str | None = "0002_document_categories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_document_type(values: tuple[str, ...]) -> None:
    op.execute(
        "ALTER TABLE documents ALTER COLUMN document_type "
        "TYPE VARCHAR(32) USING document_type::text"
    )
    op.execute("DROP TYPE document_type")
    enum_values = ", ".join(f"'{value}'" for value in values)
    op.execute(f"CREATE TYPE document_type AS ENUM ({enum_values})")
    op.execute(
        "ALTER TABLE documents ALTER COLUMN document_type "
        "TYPE document_type USING document_type::document_type"
    )


def upgrade() -> None:
    _replace_document_type(("REGISTRATION", "TAX", "INSURANCE"))


def downgrade() -> None:
    _replace_document_type(
        ("REGISTRATION", "INCORPORATION", "TAX", "BANK", "INSURANCE")
    )
