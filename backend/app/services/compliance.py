import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import (
    AuditEvent,
    ComplianceResult,
    ComplianceStatus,
    DocumentType,
    ExtractedField,
    ProcessingStatus,
    Supplier,
)
from app.services.document_policy import required_types_for

RULE_ORDER = (
    "document_completeness",
    "insurance_expiry",
    "contact_email",
    "supplier_name_match",
    "redaction_boundary",
    "field_review",
)


@dataclass(frozen=True)
class RuleOutcome:
    rule_code: str
    status: ComplianceStatus
    message: str
    evidence: dict


def _field_by_name(supplier: Supplier, field_name: str) -> ExtractedField | None:
    return next(
        (field for field in supplier.extracted_fields if field.field_name == field_name),
        None,
    )


def _parse_date(value: str) -> date | None:
    normalized = " ".join(value.strip().replace(",", " ").split())
    for format_string in (
        "%d %b %Y",
        "%d %B %Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
    ):
        try:
            return datetime.strptime(normalized, format_string).date()
        except ValueError:
            continue
    return None


def _normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def evaluate_compliance(
    supplier: Supplier,
    *,
    today: date | None = None,
) -> list[RuleOutcome]:
    today = today or datetime.now(UTC).date()
    required_types = required_types_for(supplier)
    ready_types = {
        document.document_type
        for document in supplier.documents
        if document.processing_status == ProcessingStatus.READY
    }
    missing_types = sorted(item.value for item in required_types - ready_types)
    completeness = RuleOutcome(
        rule_code="document_completeness",
        status=(ComplianceStatus.PASS if not missing_types else ComplianceStatus.FAIL),
        message=(
            "All required document categories are ready."
            if not missing_types
            else f"Missing ready document categories: {', '.join(missing_types)}."
        ),
        evidence={
            "ready_document_types": sorted(item.value for item in ready_types),
            "missing_document_types": missing_types,
        },
    )

    insurance_required = DocumentType.INSURANCE in required_types
    expiry_field = _field_by_name(supplier, "insurance_expiry_date") if insurance_required else None
    expiry_date = _parse_date(expiry_field.value) if expiry_field else None
    if not insurance_required:
        expiry_status = ComplianceStatus.PASS
        expiry_message = "Not applicable: insurance is not in this application's required checklist."
    elif expiry_field is None:
        expiry_status = ComplianceStatus.FAIL
        expiry_message = "Insurance expiry date is missing."
    elif expiry_date is None:
        expiry_status = ComplianceStatus.NEEDS_REVIEW
        expiry_message = "Insurance expiry date could not be parsed."
    elif expiry_date <= today:
        expiry_status = ComplianceStatus.FAIL
        expiry_message = "Insurance is expired or expires today."
    elif expiry_field.needs_review:
        expiry_status = ComplianceStatus.NEEDS_REVIEW
        expiry_message = "Insurance expiry is future-dated but needs reviewer confirmation."
    else:
        expiry_status = ComplianceStatus.PASS
        expiry_message = f"Insurance is valid through {expiry_date.isoformat()}."
    insurance_expiry = RuleOutcome(
        rule_code="insurance_expiry",
        status=expiry_status,
        message=expiry_message,
        evidence={
            "field_id": str(expiry_field.id) if expiry_field else None,
            "source_document_id": (
                str(expiry_field.document_id) if expiry_field else None
            ),
            "parsed_expiry": expiry_date.isoformat() if expiry_date else None,
            "checked_date": today.isoformat(),
            "not_applicable": not insurance_required,
        },
    )

    email_field = _field_by_name(supplier, "contact_email")
    email_valid = False
    if email_field is not None:
        try:
            TypeAdapter(EmailStr).validate_python(email_field.value)
            email_valid = True
        except ValidationError:
            email_valid = False
    if email_field is None:
        email_status = ComplianceStatus.FAIL
        email_message = "Contact email is missing."
    elif not email_valid:
        email_status = ComplianceStatus.FAIL
        email_message = "Contact email is not valid."
    elif email_field.needs_review:
        email_status = ComplianceStatus.NEEDS_REVIEW
        email_message = "Contact email is valid but needs reviewer confirmation."
    else:
        email_status = ComplianceStatus.PASS
        email_message = "A valid reviewed contact email is available."
    contact_email = RuleOutcome(
        rule_code="contact_email",
        status=email_status,
        message=email_message,
        evidence={
            "field_id": str(email_field.id) if email_field else None,
            "source_document_id": str(email_field.document_id) if email_field else None,
            "valid_format": email_valid,
        },
    )

    name_field = _field_by_name(supplier, "supplier_name")
    canonical_name = _normalized_name(name_field.value) if name_field else ""
    matching_documents = []
    mismatched_documents = []
    if canonical_name:
        for document in supplier.documents:
            document_text = _normalized_name(document.extracted_text or "")
            target = (
                matching_documents
                if canonical_name in document_text
                else mismatched_documents
            )
            target.append(document.filename)
    if name_field is None:
        name_status = ComplianceStatus.FAIL
        name_message = "Canonical supplier name is missing."
    elif mismatched_documents or name_field.needs_review:
        name_status = ComplianceStatus.NEEDS_REVIEW
        name_message = "Supplier name needs review across uploaded documents."
    else:
        name_status = ComplianceStatus.PASS
        name_message = "Supplier name matches all uploaded documents."
    supplier_name_match = RuleOutcome(
        rule_code="supplier_name_match",
        status=name_status,
        message=name_message,
        evidence={
            "field_id": str(name_field.id) if name_field else None,
            "matching_documents": matching_documents,
            "documents_requiring_review": mismatched_documents,
        },
    )

    unredacted_documents = [
        document.filename
        for document in supplier.documents
        if document.redacted_text is None or document.redaction_summary is None
    ]
    redaction_counts: dict[str, int] = {}
    for document in supplier.documents:
        for category, count in (document.redaction_summary or {}).items():
            redaction_counts[category] = redaction_counts.get(category, 0) + count
    redaction_boundary = RuleOutcome(
        rule_code="redaction_boundary",
        status=(
            ComplianceStatus.PASS
            if supplier.documents and not unredacted_documents
            else ComplianceStatus.FAIL
        ),
        message=(
            "PII boundary redaction was applied to every uploaded document."
            if supplier.documents and not unredacted_documents
            else "One or more documents have not passed boundary redaction."
        ),
        evidence={
            "documents_without_redaction": unredacted_documents,
            "redaction_counts": redaction_counts,
        },
    )

    unresolved_fields = sorted(
        field.field_name for field in supplier.extracted_fields if field.needs_review
    )
    if not supplier.extracted_fields:
        field_status = ComplianceStatus.FAIL
        field_message = "No extracted fields are available for review."
    elif unresolved_fields:
        field_status = ComplianceStatus.NEEDS_REVIEW
        field_message = "One or more extracted fields require reviewer confirmation."
    else:
        field_status = ComplianceStatus.PASS
        field_message = "All extracted fields have been reviewed."
    field_review = RuleOutcome(
        rule_code="field_review",
        status=field_status,
        message=field_message,
        evidence={"unresolved_fields": unresolved_fields},
    )

    return [
        completeness,
        insurance_expiry,
        contact_email,
        supplier_name_match,
        redaction_boundary,
        field_review,
    ]


def persist_compliance_results(
    db: Session,
    supplier: Supplier,
    outcomes: list[RuleOutcome],
) -> list[ComplianceResult]:
    db.execute(
        delete(ComplianceResult).where(ComplianceResult.supplier_id == supplier.id)
    )
    results = [
        ComplianceResult(
            supplier_id=supplier.id,
            rule_code=outcome.rule_code,
            status=outcome.status,
            message=outcome.message,
            evidence=outcome.evidence,
        )
        for outcome in outcomes
    ]
    db.add_all(results)
    db.add(
        AuditEvent(
            supplier_id=supplier.id,
            action="compliance.checked",
            entity_type="supplier",
            entity_id=str(supplier.id),
            details={
                "results": {
                    outcome.rule_code: outcome.status.value for outcome in outcomes
                }
            },
        )
    )
    db.flush()
    return results


def approval_ready(results: list[ComplianceResult] | list[RuleOutcome]) -> bool:
    return bool(results) and all(result.status == ComplianceStatus.PASS for result in results)
