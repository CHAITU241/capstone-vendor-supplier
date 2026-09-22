from dataclasses import dataclass

from app.models import DocumentType, ExtractedField, Supplier


@dataclass(frozen=True)
class ErpPreview:
    payload: dict
    sources: dict[str, dict]


FIELD_SOURCE_PRIORITY: dict[str, tuple[DocumentType, ...]] = {
    "supplier_name": (DocumentType.REGISTRATION, DocumentType.TAX),
    "tax_identifier": (DocumentType.TAX, DocumentType.REGISTRATION),
    "bank_account_number": (DocumentType.BANK,),
    "bank_ifsc": (DocumentType.BANK,),
    "insurance_provider": (DocumentType.INS_CYB_001, DocumentType.INS_PI_001, DocumentType.INSURANCE),
    "insurance_expiry_date": (DocumentType.INS_CYB_001, DocumentType.INS_PI_001, DocumentType.INSURANCE),
}


def _reviewed_field(supplier: Supplier, field_name: str) -> ExtractedField | None:
    documents = {document.id: document.document_type for document in supplier.documents}
    priorities = FIELD_SOURCE_PRIORITY.get(field_name, tuple(DocumentType))
    candidates = [
        field for field in supplier.extracted_fields
        if field.field_name == field_name
        and field.review_status in {"verified", "corrected"}
    ]
    if not candidates:
        return None

    def rank(field: ExtractedField) -> tuple[int, int, float]:
        document_type = documents.get(field.document_id)
        try:
            source_rank = len(priorities) - priorities.index(document_type)
        except ValueError:
            source_rank = 0
        return field.review_status == "corrected", source_rank, field.confidence

    return max(candidates, key=rank)


def build_erp_preview(supplier: Supplier) -> ErpPreview:
    payload: dict = {}
    sources: dict[str, dict] = {}

    def system(field_name: str, value) -> None:
        payload[field_name] = value
        sources[field_name] = {"source": "system_generated", "label": "System generated"}

    def supplier_value(field_name: str, value) -> None:
        payload[field_name] = value
        sources[field_name] = {
            "source": "supplier_entered" if value not in {None, ""} else "not_available",
            "label": "Supplier entered" if value not in {None, ""} else "Not available",
        }

    def reviewed_or_supplier(field_name: str, extracted_name: str, fallback) -> None:
        field = _reviewed_field(supplier, extracted_name)
        if field is None:
            supplier_value(field_name, fallback)
            return
        payload[field_name] = field.value
        sources[field_name] = {
            "source": "reviewed_evidence",
            "label": "Reviewed evidence",
            "field_id": str(field.id),
            "document_id": str(field.document_id),
            "review_status": field.review_status,
        }

    system("supplier_reference", f"SUP-{supplier.id.hex[:8].upper()}")
    reviewed_or_supplier("legal_name", "supplier_name", supplier.name)
    reviewed_or_supplier("registered_address", "address", None)
    reviewed_or_supplier("country", "country", supplier.country)
    reviewed_or_supplier("tax_reference", "tax_identifier", supplier.tax_reference)
    reviewed_or_supplier("contact_name", "contact_name", None)
    reviewed_or_supplier("contact_email", "contact_email", supplier.contact_email)
    reviewed_or_supplier("bank_account_number", "bank_account_number", supplier.bank_account_number)
    reviewed_or_supplier("bank_ifsc", "bank_ifsc", supplier.bank_ifsc)
    supplier_value("category", supplier.category)
    supplier_value("subcategory", supplier.subcategory)
    reviewed_or_supplier("insurance_provider", "insurance_provider", None)
    reviewed_or_supplier("insurance_expiry_date", "insurance_expiry_date", None)
    reviewed_or_supplier("payment_terms", "payment_terms", None)
    return ErpPreview(payload=payload, sources=sources)
