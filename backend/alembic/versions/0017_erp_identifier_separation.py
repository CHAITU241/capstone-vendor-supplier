"""Separate portal, ERP record, and final Vendor identifiers."""

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_erp_identifier_separation"
down_revision: str | None = "0016_ocr_quality"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _candidate(key: str) -> int:
    return 1_000_000_000 + (
        int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], 16)
        % 9_000_000_000
    )


def upgrade() -> None:
    op.add_column("suppliers", sa.Column("erp_record_id", sa.String(100), nullable=True))
    op.create_index(
        "ix_suppliers_erp_record_id",
        "suppliers",
        ["erp_record_id"],
        unique=True,
    )

    bind = op.get_bind()
    records = bind.execute(sa.text(
        "SELECT id, idempotency_key, source_supplier_id FROM erp_supplier_records"
    )).mappings().all()
    used: set[int] = set()
    for record in records:
        vendor_number = _candidate(str(record["idempotency_key"]))
        while vendor_number in used:
            vendor_number = 1_000_000_000 + (
                (vendor_number - 999_999_999) % 9_000_000_000
            )
        used.add(vendor_number)
        compact_record_id = str(record["id"]).replace("-", "")[:12].upper()
        erp_record_id = f"ERP-REC-{compact_record_id}"
        bind.execute(
            sa.text(
                "UPDATE erp_supplier_records "
                "SET erp_supplier_id = :vendor_id WHERE id = :record_id"
            ),
            {"vendor_id": str(vendor_number), "record_id": record["id"]},
        )
        bind.execute(
            sa.text(
                "UPDATE suppliers SET erp_supplier_id = :vendor_id, "
                "erp_record_id = :erp_record_id WHERE id = :supplier_id"
            ),
            {
                "vendor_id": str(vendor_number),
                "erp_record_id": erp_record_id,
                "supplier_id": record["source_supplier_id"],
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    records = bind.execute(sa.text(
        "SELECT id, idempotency_key, source_supplier_id FROM erp_supplier_records"
    )).mappings().all()
    for record in records:
        legacy_id = "ERP-" + hashlib.sha256(
            str(record["idempotency_key"]).encode("utf-8")
        ).hexdigest()[:10].upper()
        bind.execute(
            sa.text(
                "UPDATE erp_supplier_records "
                "SET erp_supplier_id = :legacy_id WHERE id = :record_id"
            ),
            {"legacy_id": legacy_id, "record_id": record["id"]},
        )
        bind.execute(
            sa.text(
                "UPDATE suppliers SET erp_supplier_id = :legacy_id "
                "WHERE id = :supplier_id"
            ),
            {
                "legacy_id": legacy_id,
                "supplier_id": record["source_supplier_id"],
            },
        )
    op.drop_index("ix_suppliers_erp_record_id", table_name="suppliers")
    op.drop_column("suppliers", "erp_record_id")
