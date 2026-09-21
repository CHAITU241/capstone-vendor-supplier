from dataclasses import dataclass
from datetime import UTC, datetime

from app.models import Supplier


@dataclass(frozen=True)
class ErpSupplierResult:
    supplier_id: str
    status: str
    completed_at: datetime
    payload: dict


class MockERPService:
    """Deterministic local ERP boundary used by the Phase 3 demo."""

    def create_supplier(self, supplier: Supplier) -> ErpSupplierResult:
        fields = {field.field_name: field.value for field in supplier.extracted_fields
                  if field.review_status in {"verified", "corrected"}}
        payload = {
            "supplier_reference": f"SUP-{supplier.id.hex[:8].upper()}",
            "legal_name": fields.get("supplier_name", supplier.name),
            "registered_address": fields.get("address"),
            "country": fields.get("country", supplier.country),
            "tax_reference": fields.get("tax_identifier", supplier.tax_reference),
            "contact_name": fields.get("contact_name"),
            "contact_email": fields.get("contact_email", supplier.contact_email),
            "bank_account_number": fields.get("bank_account_number", supplier.bank_account_number),
            "bank_ifsc": fields.get("bank_ifsc", supplier.bank_ifsc),
            "category": supplier.category,
            "subcategory": supplier.subcategory,
            "insurance_provider": fields.get("insurance_provider"),
            "insurance_expiry_date": fields.get("insurance_expiry_date"),
            "payment_terms": fields.get("payment_terms"),
        }
        return ErpSupplierResult(
            supplier_id=f"ERP-{supplier.id.hex[:10].upper()}",
            status="created",
            completed_at=datetime.now(UTC),
            payload=payload,
        )


def get_mock_erp_service() -> MockERPService:
    return MockERPService()
