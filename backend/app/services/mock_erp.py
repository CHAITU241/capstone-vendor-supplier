from dataclasses import dataclass
from datetime import UTC, datetime

from app.models import Supplier


@dataclass(frozen=True)
class ErpSupplierResult:
    supplier_id: str
    status: str
    completed_at: datetime


class MockERPService:
    """Deterministic local ERP boundary used by the Phase 3 demo."""

    def create_supplier(self, supplier: Supplier) -> ErpSupplierResult:
        return ErpSupplierResult(
            supplier_id=f"ERP-{supplier.id.hex[:10].upper()}",
            status="created",
            completed_at=datetime.now(UTC),
        )


def get_mock_erp_service() -> MockERPService:
    return MockERPService()
