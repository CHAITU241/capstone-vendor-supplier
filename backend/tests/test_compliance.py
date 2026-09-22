import uuid
from datetime import date, datetime, timezone

from app.models import (
    ComplianceStatus,
    Document,
    DocumentType,
    ExtractedField,
    ProcessingStatus,
    Supplier,
)
from app.services.compliance import approval_ready, evaluate_compliance
from app.services.document_policy import checklist_for, extraction_field_names
from app.services.mock_erp import MockERPService, build_erp_preview


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
        review_status="verified",
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
        review_status="attention" if needs_review else "verified",
    )


def ready_supplier() -> Supplier:
    supplier = Supplier(
        id=uuid.uuid4(),
        name=SUPPLIER_NAME,
        country="India",
        contact_email="reviewer@example.com",
        submitted_at=datetime.now(timezone.utc),
        requirements_snapshot={
            "version": "legacy-demo", "status": "illustrative_demo", "reason": "Historical snapshot",
            "documents": [{"document_type": kind, "label": kind.title(), "why": "Legacy demo"}
                          for kind in ("registration", "tax", "insurance")],
        },
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
    supplier.requirements_snapshot["documents"] = supplier.requirements_snapshot["documents"][:2]
    supplier.documents = supplier.documents[:2]
    supplier.extracted_fields = [
        item for item in supplier.extracted_fields if item.field_name != "insurance_expiry_date"
    ]

    outcomes = outcomes_by_code(supplier)

    assert outcomes["document_completeness"].status == ComplianceStatus.PASS
    assert outcomes["insurance_expiry"].status == ComplianceStatus.PASS
    assert outcomes["insurance_expiry"].evidence["not_applicable"] is True


def test_policy_uploads_are_not_misreported_as_validated() -> None:
    supplier = ready_supplier()
    supplier.category = "GOODS"
    supplier.subcategory = "GOODS-OFF"
    supplier.submitted_at = None
    supplier.documents = [document(DocumentType.REGISTRATION), document(DocumentType.TAX), document(DocumentType.BANK)]
    for item in supplier.documents:
        item.review_status = "pending"

    outcomes = outcomes_by_code(supplier)

    assert outcomes["BASE-001.CHECK-1"].status == ComplianceStatus.NEEDS_REVIEW
    assert outcomes["BASE-001.CHECK-2"].evidence["check_text"].endswith("status is Active.")
    assert outcomes["BASE-003.CHECK-1"].evidence["source"].endswith("§BASE-003")
    assert approval_ready(list(outcomes.values())) is False


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
    assert first.payload["legal_name"] == SUPPLIER_NAME
    assert first.payload["supplier_reference"].startswith("SUP-")


def test_policy_checks_pass_after_human_evidence_review() -> None:
    supplier = ready_supplier()
    supplier.category = "GOODS"
    supplier.subcategory = "GOODS-OFF"
    supplier.submitted_at = None
    supplier.documents = [document(DocumentType.REGISTRATION), document(DocumentType.TAX), document(DocumentType.BANK)]

    outcomes = outcomes_by_code(supplier)

    for requirement in ("BASE-001", "BASE-002", "BASE-003"):
        assert outcomes[f"{requirement}.CHECK-1"].status == ComplianceStatus.PASS
        assert outcomes[f"{requirement}.CHECK-2"].status == ComplianceStatus.PASS


def test_pending_ai_values_do_not_override_supplier_erp_data() -> None:
    supplier = ready_supplier()
    supplier.tax_reference = "PORTAL-PAN-001"
    source = supplier.documents[1]
    pending = field(supplier, source, "tax_identifier", "AI-PAN-999")
    pending.review_status = "pending"
    supplier.extracted_fields.append(pending)

    preview = build_erp_preview(supplier)

    assert preview.payload["tax_reference"] == "PORTAL-PAN-001"
    assert preview.sources["tax_reference"]["source"] == "supplier_entered"


def test_verified_ai_values_are_the_exact_erp_preview_values() -> None:
    supplier = ready_supplier()
    supplier.tax_reference = "PORTAL-PAN-001"
    source = supplier.documents[1]
    supplier.extracted_fields.append(
        field(supplier, source, "tax_identifier", "VERIFIED-PAN-002")
    )

    preview = build_erp_preview(supplier)
    result = MockERPService().create_supplier(supplier)

    assert preview.payload["tax_reference"] == "VERIFIED-PAN-002"
    assert preview.sources["tax_reference"]["source"] == "reviewed_evidence"
    assert result.payload == preview.payload


def test_aster_cloudworks_style_happy_path_passes_after_human_review() -> None:
    supplier = Supplier(
        id=uuid.uuid4(),
        name="Aster Cloudworks 001 Pvt Ltd",
        country="India",
        contact_email="onboarding001@supplier.example",
        tax_reference="DEMO-PAN-0001",
        bank_account_number="9900000000001",
        bank_ifsc="DEMO0001234",
        category="TECH",
        subcategory="TECH-SW",
    )
    supplier.documents = [
        document(item.document_type) for item in checklist_for(supplier).documents
    ]
    supplier.extracted_fields = [
        field(supplier, source, field_name, f"Demo {field_name}")
        for source in supplier.documents
        for field_name in extraction_field_names(source.document_type)
    ]

    outcomes = evaluate_compliance(supplier, today=date(2026, 9, 22))

    policy_checks = [
        outcome for outcome in outcomes
        if outcome.evidence.get("kind") == "policy_check"
    ]
    assert len(policy_checks) == 14
    assert all(outcome.status == ComplianceStatus.PASS for outcome in outcomes)
    assert approval_ready(outcomes) is True
