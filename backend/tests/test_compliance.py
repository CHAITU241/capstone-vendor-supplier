import uuid
from datetime import date

from app.models import (
    ComplianceStatus,
    Document,
    DocumentType,
    ExtractedField,
    ProcessingStatus,
    Supplier,
)
from app.services.compliance import approval_ready, evaluate_compliance
from app.services.mock_erp import MockERPService


SUPPLIER_NAME = "Asteron Industrial Components Private Limited"


def document(document_type: DocumentType) -> Document:
    return Document(
        id=uuid.uuid4(),
        document_type=document_type,
        filename=f"{document_type.value}.pdf",
        storage_path=f"uploads/{document_type.value}.pdf",
        content_type="application/pdf",
        file_size=100,
        page_count=1,
        extracted_text=f"Named supplier: {SUPPLIER_NAME}",
        redacted_text=f"Named supplier: {SUPPLIER_NAME}",
        redaction_summary={},
        processing_status=ProcessingStatus.READY,
    )


def field(
    supplier: Supplier,
    source: Document,
    field_name: str,
    value: str,
    *,
    needs_review: bool = False,
) -> ExtractedField:
    return ExtractedField(
        id=uuid.uuid4(),
        supplier=supplier,
        document=source,
        field_name=field_name,
        value=value,
        page_number=1,
        confidence=0.95,
        needs_review=needs_review,
    )


def ready_supplier() -> Supplier:
    supplier = Supplier(
        id=uuid.uuid4(),
        name=SUPPLIER_NAME,
        country="India",
        contact_email="reviewer@example.com",
    )
    registration = document(DocumentType.REGISTRATION)
    tax = document(DocumentType.TAX)
    insurance = document(DocumentType.INSURANCE)
    supplier.documents = [registration, tax, insurance]
    supplier.extracted_fields = [
        field(supplier, registration, "supplier_name", SUPPLIER_NAME),
        field(supplier, registration, "contact_email", "reviewer@example.com"),
        field(supplier, insurance, "insurance_expiry_date", "31 MAR 2027"),
        field(supplier, registration, "country", "India"),
    ]
    return supplier


def outcomes_by_code(supplier: Supplier) -> dict:
    return {
        item.rule_code: item
        for item in evaluate_compliance(supplier, today=date(2026, 8, 4))
    }


def test_happy_path_passes_all_compliance_rules() -> None:
    outcomes = evaluate_compliance(ready_supplier(), today=date(2026, 8, 4))

    assert len(outcomes) == 6
    assert all(item.status == ComplianceStatus.PASS for item in outcomes)
    assert approval_ready(outcomes) is True


def test_expired_insurance_blocks_approval() -> None:
    supplier = ready_supplier()
    expiry = next(
        item
        for item in supplier.extracted_fields
        if item.field_name == "insurance_expiry_date"
    )
    expiry.value = "01 JAN 2026"

    outcomes = outcomes_by_code(supplier)

    assert outcomes["insurance_expiry"].status == ComplianceStatus.FAIL
    assert approval_ready(list(outcomes.values())) is False


def test_insurance_check_is_not_applicable_when_checklist_omits_it() -> None:
    supplier = ready_supplier()
    supplier.category = "Technology & IT"
    supplier.subcategory = "Software & SaaS"
    supplier.documents = supplier.documents[:2]
    supplier.extracted_fields = [
        item for item in supplier.extracted_fields if item.field_name != "insurance_expiry_date"
    ]

    outcomes = outcomes_by_code(supplier)

    assert outcomes["document_completeness"].status == ComplianceStatus.PASS
    assert outcomes["insurance_expiry"].status == ComplianceStatus.PASS
    assert outcomes["insurance_expiry"].evidence["not_applicable"] is True


def test_name_mismatch_and_unresolved_field_need_review() -> None:
    supplier = ready_supplier()
    supplier.documents[-1].extracted_text = "Named supplier: Different Legal Entity"
    supplier.extracted_fields[-1].needs_review = True

    outcomes = outcomes_by_code(supplier)

    assert outcomes["supplier_name_match"].status == ComplianceStatus.NEEDS_REVIEW
    assert outcomes["field_review"].status == ComplianceStatus.NEEDS_REVIEW


def test_invalid_email_fails_deterministically() -> None:
    supplier = ready_supplier()
    contact = next(
        item for item in supplier.extracted_fields if item.field_name == "contact_email"
    )
    contact.value = "not-an-email"

    assert outcomes_by_code(supplier)["contact_email"].status == ComplianceStatus.FAIL


def test_mock_erp_reference_is_deterministic() -> None:
    supplier = ready_supplier()

    first = MockERPService().create_supplier(supplier)
    second = MockERPService().create_supplier(supplier)

    assert first.supplier_id == second.supplier_id
    assert first.supplier_id.startswith("ERP-")
