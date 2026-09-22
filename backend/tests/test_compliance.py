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
from app.services.mock_erp import build_erp_preview


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
        supplier_id=supplier.id,
        document_id=source.id,
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


def test_objective_privacy_rules_override_model_policy_opinions() -> None:
    supplier = Supplier(
        id=uuid.uuid4(),
        name="Brindle Cyber Shield 002 Pvt Ltd",
        country="India",
        category="TECH",
        subcategory="TECH-CYB",
    )
    supplier.documents = [
        document(item.document_type) for item in checklist_for(supplier).documents
    ]
    for item in supplier.documents:
        item.review_status = "pending"
        item.ai_extraction_status = "ready"
    privacy = next(
        item for item in supplier.documents
        if item.document_type == DocumentType.PRIV_001
    )
    supplier.extracted_fields = [
        field(supplier, privacy, field_name, "None" if field_name == "subprocessors" else "Demo value")
        for field_name in extraction_field_names(DocumentType.PRIV_001)
    ]

    outcomes = {
        item.rule_code: item for item in evaluate_compliance(
            supplier,
            ai_policy_assessments=[
                {
                    "document_id": str(privacy.id),
                    "requirement_id": "PRIV-001",
                    "check_number": 1,
                    "result": "matched",
                    "reason": "Every privacy field is answered and subprocessors are explicitly None.",
                    "evidence_fields": ["subprocessors"],
                    "page_number": 1,
                },
                {
                    "document_id": str(privacy.id),
                    "requirement_id": "PRIV-001",
                    "check_number": 2,
                    "result": "not_matched",
                    "reason": "The deletion interval is 45 days, above the 30-day limit.",
                    "evidence_fields": ["Deletion Interval"],
                    "page_number": 1,
                },
            ],
        )
    }

    matched = outcomes["PRIV-001.CHECK-1"]
    mismatch = outcomes["PRIV-001.CHECK-2"]
    assert matched.status == ComplianceStatus.NEEDS_REVIEW
    assert matched.evidence["ai_assessment"] == "matched"
    assert matched.evidence["assessment_method"] == "deterministic"
    assert "subprocessors" in matched.evidence["evidence_fields"]
    assert mismatch.status == ComplianceStatus.NEEDS_REVIEW
    assert mismatch.evidence["ai_assessment"] == "human_review"
    assert mismatch.evidence["assessment_method"] == "deterministic"
    assert "ambiguous" in mismatch.evidence["ai_reason"]
    assert mismatch.evidence["expected_values"][0]["source"] == "Policy check"
    assert "30 calendar days" in mismatch.evidence["expected_values"][0]["value"]


def test_brindle_objective_checks_ignore_five_false_model_mismatches() -> None:
    supplier = Supplier(
        id=uuid.uuid4(),
        name="Brindle Cyber Shield 002 Pvt Ltd",
        country="India",
        tax_reference="DEMO-PAN-0002",
        bank_account_number="990000000002",
        bank_ifsc="DEMO0001234",
        category="TECH",
        subcategory="TECH-CYB",
    )
    supplier.documents = [document(item.document_type) for item in checklist_for(supplier).documents]
    for item in supplier.documents:
        item.review_status = "pending"
        item.ai_extraction_status = "ready"

    by_type = {item.document_type: item for item in supplier.documents}
    values = {
        DocumentType.REGISTRATION: {
            "supplier_name": supplier.name,
            "registration_date": "2021-04-12",
            "status": "Active",
        },
        DocumentType.BANK: {
            "supplier_name": supplier.name,
            "bank_account_number": supplier.bank_account_number,
            "bank_ifsc": supplier.bank_ifsc,
            "document_date": "2026-08-30",
        },
        DocumentType.CONF_001: {
            "supplier_name": supplier.name,
            "both_signatures": "/s/ A. Rao 002, /s/ S. Iyer",
            "execution_date": "2026-08-20",
        },
        DocumentType.SEC_001: {
            "incident_notice_commitment": "24 hours",
            "signature_and_date": "/s/ A. Rao 002; 2026-09-05",
        },
        DocumentType.CONT_001: {
            "last_exercise_date": "2026-06-11",
            "review_date": "2026-08-20",
        },
    }
    supplier.extracted_fields = [
        field(supplier, by_type[document_type], field_name, value)
        for document_type, document_values in values.items()
        for field_name, value in document_values.items()
    ]
    false_model_findings = [
        {
            "document_id": str(by_type[document_type].id),
            "requirement_id": requirement_id,
            "check_number": check_number,
            "result": "not_matched",
            "reason": "Incorrect model conclusion.",
            "evidence_fields": evidence_fields,
            "page_number": 1,
        }
        for document_type, requirement_id, check_number, evidence_fields in (
            (DocumentType.BANK, "BASE-003", 2, ["Document Date"]),
            (DocumentType.CONF_001, "CONF-001", 1, ["Supplier Name", "Both Signatures"]),
            (DocumentType.CONF_001, "CONF-001", 2, ["Execution Date"]),
            (DocumentType.SEC_001, "SEC-001", 2, ["Incident Notice Commitment", "Signature And Date"]),
            (DocumentType.CONT_001, "CONT-001", 2, ["Last Exercise Date", "Review Date"]),
        )
    ]

    outcomes = {
        item.rule_code: item
        for item in evaluate_compliance(
            supplier,
            today=date(2026, 9, 22),
            ai_policy_assessments=false_model_findings,
        )
    }

    for rule_code in (
        "BASE-003.CHECK-2",
        "CONF-001.CHECK-1",
        "CONF-001.CHECK-2",
        "SEC-001.CHECK-2",
        "CONT-001.CHECK-2",
    ):
        assert outcomes[rule_code].evidence["ai_assessment"] == "matched"
        assert outcomes[rule_code].evidence["assessment_method"] == "deterministic"
        assert "Incorrect model conclusion" not in outcomes[rule_code].evidence["ai_reason"]


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
    assert preview.payload["tax_reference"] == "VERIFIED-PAN-002"
    assert preview.sources["tax_reference"]["source"] == "reviewed_evidence"


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
