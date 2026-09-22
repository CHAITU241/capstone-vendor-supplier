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
from app.services.document_policy import (
    checklist_for,
    required_extraction_field_names,
    required_types_for,
)
from app.services.policy_evaluator import evaluate_objective_check

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


def _normalized_field_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _policy_value_details(
    supplier: Supplier,
    document_fields: dict[str, ExtractedField],
    cited_fields: list[str],
    missing_fields: list[str],
    check_text: str,
) -> tuple[list[dict], list[dict]]:
    """Expose reviewer-friendly values without sending portal secrets back to the AI."""
    observed = [
        {
            "field_name": name,
            "value": document_fields[name].value,
            "page_number": document_fields[name].page_number,
        }
        for name in cited_fields
        if name in document_fields
    ]
    observed.extend({"field_name": name, "value": None, "page_number": None} for name in missing_fields)

    portal_values = {
        "supplier_name": supplier.name,
        "tax_identifier": supplier.tax_reference,
        "bank_account_number": supplier.bank_account_number,
        "bank_ifsc": supplier.bank_ifsc,
        "contact_email": supplier.contact_email,
        "country": "India",
    }
    expected = [
        {"field_name": name, "value": portal_values[name], "source": "Portal value"}
        for name in dict.fromkeys([*cited_fields, *missing_fields])
        if name in portal_values and portal_values[name]
    ]
    expected.append({"field_name": "policy_rule", "value": check_text, "source": "Policy check"})
    return observed, expected


def _policy_assessment_lookup(
    supplier: Supplier,
    current_assessments: list[dict] | None,
) -> dict[tuple[str, int], dict]:
    """Prefer the current run, then retain the newest finding for untouched documents."""
    lookup: dict[tuple[str, int], dict] = {}

    def add(items: object) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            document_id = item.get("document_id")
            check_number = item.get("check_number")
            result = item.get("result")
            if (
                isinstance(document_id, str)
                and isinstance(check_number, int)
                and result in {"matched", "not_matched", "human_review"}
            ):
                lookup.setdefault((document_id, check_number), item)

    add(current_assessments)
    for run in sorted(
        getattr(supplier, "ai_runs", []),
        key=lambda item: item.created_at,
        reverse=True,
    ):
        if run.run_type.value == "processing" and isinstance(run.details, dict):
            add(run.details.get("policy_assessments"))
    return lookup


def _evaluate_policy_compliance(
    supplier: Supplier,
    evaluation_date: date,
    ai_policy_assessments: list[dict] | None = None,
) -> list[RuleOutcome]:
    """Combine provisional AI findings with the authoritative human review state."""
    checklist = checklist_for(supplier)
    fields_by_document: dict = {}
    for field in supplier.extracted_fields:
        fields_by_document.setdefault(field.document_id, {})[field.field_name] = field
    assessment_lookup = _policy_assessment_lookup(supplier, ai_policy_assessments)
    registration_document = next(
        (candidate for candidate in supplier.documents
         if candidate.document_type == DocumentType.REGISTRATION),
        None,
    )
    registration_fields = fields_by_document.get(registration_document.id, {}) if registration_document else {}
    baseline_name_field = registration_fields.get("supplier_name")
    baseline_name = baseline_name_field.value if baseline_name_field else None

    outcomes: list[RuleOutcome] = []
    for item in checklist.documents:
        document = next(
            (candidate for candidate in supplier.documents
             if candidate.document_type == item.document_type),
            None,
        )
        expected_fields = required_extraction_field_names(item.document_type)
        document_fields = fields_by_document.get(document.id, {}) if document else {}
        found_fields = set(document_fields)
        missing_fields = sorted(set(expected_fields) - found_fields)

        for check_number, check_text in enumerate(item.checks, start=1):
            cited_fields: list[str] = []
            cited_page = None
            assessment_method = "deterministic"
            if document is None or document.processing_status != ProcessingStatus.READY:
                status = ComplianceStatus.FAIL
                message = "Required evidence is missing or unreadable."
                ai_assessment = "not_matched"
                ai_reason = message
            elif document.review_status == "disputed":
                assessment_method = "reviewer"
                status = ComplianceStatus.FAIL
                message = "The reviewer flagged this evidence as not satisfying the requirement."
                ai_assessment = "reviewer_flagged"
                ai_reason = message
                cited_fields = []
                cited_page = None
            elif document.review_status == "verified":
                assessment_method = "reviewer"
                status = ComplianceStatus.PASS
                message = "Reviewer verified this numbered policy check against the original evidence."
                ai_assessment = "human_verified"
                ai_reason = message
                cited_fields = []
                cited_page = None
            elif document.ai_extraction_status == "failed":
                assessment_method = "human_required"
                status = ComplianceStatus.NEEDS_REVIEW
                message = "AI assessment is unavailable; verify this check directly against the original evidence."
                ai_assessment = "human_review"
                ai_reason = message
                cited_fields = []
                cited_page = None
            else:
                values = {name: field.value for name, field in document_fields.items()}
                objective = evaluate_objective_check(
                    item.requirement_id,
                    check_number,
                    values,
                    baseline_name=baseline_name,
                    portal_name=supplier.name,
                    portal_tax_reference=supplier.tax_reference,
                    portal_bank_account=supplier.bank_account_number,
                    portal_bank_ifsc=supplier.bank_ifsc,
                    evaluation_date=evaluation_date,
                )
                assessment = assessment_lookup.get((str(document.id), check_number))
                if objective is not None:
                    cited_fields = [name for name in objective.evidence_fields if name in document_fields]
                    assessment_result = objective.result
                    assessment_reason = objective.reason
                else:
                    assessment_method = "ai_semantic"
                    field_aliases = {
                        _normalized_field_key(name): name for name in document_fields
                    }
                    cited_fields = list(dict.fromkeys(
                        canonical
                        for name in (assessment or {}).get("evidence_fields", [])
                        if isinstance(name, str)
                        for canonical in [field_aliases.get(_normalized_field_key(name))]
                        if canonical is not None
                    ))
                    cited_page = (assessment or {}).get("page_number")
                    assessment_result = str((assessment or {}).get("result") or "human_review")
                    assessment_reason = str((assessment or {}).get("reason") or "AI did not produce a semantic conclusion; inspect the original evidence.")
                low_confidence = any(
                    document_fields[name].needs_review
                    or document_fields[name].confidence < 0.75
                    for name in cited_fields
                )
                if low_confidence:
                    status = ComplianceStatus.NEEDS_REVIEW
                    ai_assessment = "human_review"
                    ai_reason = "The cited extracted evidence has low confidence and requires human confirmation."
                elif assessment_result == "not_matched":
                    status = ComplianceStatus.FAIL
                    ai_assessment = "not_matched"
                    ai_reason = assessment_reason
                elif assessment_result == "matched":
                    status = ComplianceStatus.NEEDS_REVIEW
                    ai_assessment = "matched"
                    ai_reason = assessment_reason
                else:
                    status = ComplianceStatus.NEEDS_REVIEW
                    ai_assessment = "human_review"
                    ai_reason = assessment_reason
                message = (
                    f"Policy evaluation found a mismatch: {ai_reason}"
                    if ai_assessment == "not_matched" else
                    f"Policy evaluation found evidence consistent with this check: {ai_reason}"
                    if ai_assessment == "matched" else
                    f"Human review required: {ai_reason}"
                )

            observed_values, expected_values = _policy_value_details(
                supplier,
                document_fields,
                cited_fields,
                missing_fields,
                check_text,
            )

            outcomes.append(RuleOutcome(
                rule_code=f"{item.requirement_id}.CHECK-{check_number}",
                status=status,
                message=message,
                evidence={
                    "kind": "policy_check",
                    "blocking": True,
                    "requirement_id": item.requirement_id,
                    "requirement_label": item.label,
                    "check_number": check_number,
                    "check_text": check_text,
                    "source": item.source,
                    "document_id": str(document.id) if document else None,
                    "review_status": document.review_status if document else "missing",
                    "ai_assessment": ai_assessment,
                    "ai_reason": ai_reason,
                    "assessment_method": assessment_method,
                    "evidence_fields": cited_fields,
                    "evidence_page": cited_page,
                    "expected_fields": expected_fields,
                    "missing_fields": missing_fields,
                    "observed_values": observed_values,
                    "expected_values": expected_values,
                },
            ))

    if supplier.extracted_fields:
        disputed = [
            field.field_name for field in supplier.extracted_fields
            if field.review_status == "disputed"
        ]
        unresolved = [
            field.field_name for field in supplier.extracted_fields
            if field.needs_review
            or field.review_status not in {"verified", "corrected"}
        ]
        if disputed:
            status = ComplianceStatus.FAIL
            message = "One or more AI-extracted values were disputed by the reviewer."
        elif unresolved:
            status = ComplianceStatus.NEEDS_REVIEW
            message = "Review or correct every AI-extracted value before approval."
        else:
            status = ComplianceStatus.PASS
            message = "All AI-extracted values were verified or corrected by the reviewer."
        outcomes.append(RuleOutcome(
            rule_code="REVIEW.EXTRACTED_FIELDS",
            status=status,
            message=message,
            evidence={
                "kind": "review_control",
                "blocking": True,
                "unresolved_fields": sorted(unresolved),
                "disputed_fields": sorted(disputed),
            },
        ))
    return outcomes


def evaluate_compliance(
    supplier: Supplier,
    *,
    today: date | None = None,
    ai_policy_assessments: list[dict] | None = None,
) -> list[RuleOutcome]:
    today = today or datetime.now(UTC).date()
    checklist = checklist_for(supplier)
    if checklist.status == "synthetic_demo_policy":
        return _evaluate_policy_compliance(supplier, today, ai_policy_assessments)

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
    elif mismatched_documents:
        name_status = ComplianceStatus.NEEDS_REVIEW
        name_message = "The supplier name was not found in one or more uploaded documents."
    elif name_field.needs_review or name_field.review_status not in {"verified", "corrected"}:
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
        field.field_name for field in supplier.extracted_fields
        if field.needs_review or field.review_status not in {"verified", "corrected"}
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

    outcomes = [
        completeness,
        insurance_expiry,
        contact_email,
        supplier_name_match,
        redaction_boundary,
        field_review,
    ]
    return outcomes


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
