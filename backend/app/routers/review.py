import uuid
import json
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from app.services.portal_auth import require_reviewer
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.config import Settings, get_settings
from app.metrics import record_compliance_checks, record_supplier_decision
from app.models import (
    AuditEvent,
    ComplianceResult,
    ComplianceStatus,
    Document,
    ExtractedField,
    Supplier,
    SupplierStatus,
)
from app.schemas import (
    ApprovalRequest,
    ConfirmReadyRequirementsRequest,
    ConfirmReadyRequirementsResponse,
    ComplianceResultRead,
    ComplianceRunResponse,
    DecisionResponse,
    DocumentRead,
    EvidenceReviewRequest,
    ErpRecordRead,
    ErpValidationResponse,
    ExtractedFieldRead,
    ExtractedFieldUpdate,
    FlagReasonDraftRead,
    OtherReviewRequest,
    OtherReviewResponse,
    ReviewSelectionRequest,
    RejectionRequest,
)
from app.services.compliance import (
    approval_ready,
    evaluate_compliance,
    persist_compliance_results,
)
from app.services.mock_erp import build_erp_preview
from app.services.erp_mcp_client import ErpMcpClient, supplier_idempotency_key
from app.services.erp_tools import ErpToolFailure
from app.services.document_policy import RequiredDocument, checklist_for
from app.services.openai_service import build_openai_service
from app.services.policy_retrieval import policy_context_for
from app.services.redaction import redact_pii
from app.services.tracing import get_langfuse_tracer, telemetry_subject_id

router = APIRouter(prefix="/suppliers", tags=["review"], dependencies=[Depends(require_reviewer)])


def _get_review_supplier(db: Session, supplier_id: uuid.UUID) -> Supplier:
    supplier = db.scalar(
        select(Supplier)
        .where(Supplier.id == supplier_id)
        .options(
            selectinload(Supplier.documents),
            selectinload(Supplier.additional_documents),
            selectinload(Supplier.extracted_fields),
            selectinload(Supplier.ai_runs),
            selectinload(Supplier.compliance_results),
        )
    )
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier was not found.")
    return supplier


def _ensure_reviewable(supplier: Supplier) -> None:
    if supplier.status in {SupplierStatus.APPROVED, SupplierStatus.REJECTED}:
        raise HTTPException(
            status_code=409,
            detail="A finalized supplier cannot be changed in this demo workflow.",
        )


def _verify_document(
    db: Session,
    supplier: Supplier,
    document: Document,
    *,
    reviewer_name: str,
    now: datetime,
    bulk_action: bool = False,
) -> None:
    document.review_status = "verified"
    document.review_comment = "Requirement confirmed against the original evidence."
    document.reviewed_by = reviewer_name
    document.reviewed_at = now
    reviewed_fields = [
        field for field in supplier.extracted_fields if field.document_id == document.id
    ]
    for field in reviewed_fields:
        if field.review_status != "corrected":
            field.review_status = "verified"
            field.review_comment = "Verified with the source requirement."
        field.needs_review = False
        field.reviewed_by = reviewer_name
        field.reviewed_at = now
    db.add(AuditEvent(
        supplier_id=supplier.id,
        action="document.verified",
        entity_type="document",
        entity_id=str(document.id),
        details={
            "reviewer_name": reviewer_name,
            "reason": None,
            "bulk_action": bulk_action,
            "extracted_field_ids": [str(field.id) for field in reviewed_fields],
            "extracted_field_count": len(reviewed_fields),
            "compliance_results_recalculated": True,
        },
    ))


def _compliance_response(results: list[ComplianceResult]) -> ComplianceRunResponse:
    ordered = sorted(results, key=lambda item: item.rule_code)
    return ComplianceRunResponse(
        results=[ComplianceResultRead.model_validate(item) for item in ordered],
        approval_ready=approval_ready(results),
    )


def _safe_finding_text(value: str, supplier: Supplier) -> str:
    for sensitive_value in (
        supplier.tax_reference,
        supplier.bank_account_number,
        supplier.bank_ifsc,
    ):
        if sensitive_value:
            value = re.sub(re.escape(sensitive_value), "the recorded value", value, flags=re.IGNORECASE)
    redacted = redact_pii(value).text
    redacted = re.sub(r"\[(?:GSTIN|PAN|CIN|EMAIL|PHONE|BANK_ACCOUNT)_\d+\]", "the recorded value", redacted)
    return " ".join(redacted.split())[:500]


def _flag_findings(supplier: Supplier, document: Document) -> list[dict]:
    findings: list[dict] = []
    for result in supplier.compliance_results:
        evidence = result.evidence if isinstance(result.evidence, dict) else {}
        related_document_ids = evidence.get("document_ids")
        applies_to_document = (
            evidence.get("document_id") == str(document.id)
            or isinstance(related_document_ids, list)
            and str(document.id) in related_document_ids
        )
        if result.status == ComplianceStatus.PASS or not applies_to_document:
            continue
        item = {
            "message": _safe_finding_text(result.message, supplier),
            "status": result.status.value,
        }
        ai_reason = evidence.get("ai_reason")
        if isinstance(ai_reason, str) and ai_reason.strip():
            item["assessment_reason"] = _safe_finding_text(ai_reason, supplier)
        missing_fields = evidence.get("missing_fields")
        if isinstance(missing_fields, list):
            item["missing_fields"] = [
                str(field).replace("_", " ") for field in missing_fields[:12]
            ]
        findings.append(item)
    disputed_fields = [
        field.field_name.replace("_", " ")
        for field in supplier.extracted_fields
        if field.document_id == document.id and field.review_status == "disputed"
    ]
    if disputed_fields:
        findings.append({
            "message": "The reviewer disputed extracted fields.",
            "disputed_fields": disputed_fields,
            "status": "needs_review",
        })
    if not findings and document.review_comment:
        findings.append({
            "message": _safe_finding_text(document.review_comment, supplier),
            "status": document.review_status,
        })
    return findings


_FIELD_LABELS = {
    "declaration date and signatory when not registered": "declaration date and authorized signature",
    "gst status registered or not registered": "GST registration status",
    "gstin when registered": "GSTIN",
    "supplier name": "supplier legal name",
    "tax identifier": "PAN or tax reference",
    "bank ifsc": "IFSC code",
    "both signatures": "both parties' signatures",
    "signature and date": "signature and date",
}


def _friendly_field(value: str) -> str:
    normalized = " ".join(value.replace("_", " ").split()).casefold()
    return _FIELD_LABELS.get(normalized, normalized)


def _human_list(values: list[str]) -> str:
    clean = list(dict.fromkeys(_friendly_field(value) for value in values if value.strip()))
    if not clean:
        return "the required information"
    if len(clean) == 1:
        return clean[0]
    return f"{', '.join(clean[:-1])} and {clean[-1]}"


def _plain_finding(value: str) -> str:
    text = " ".join(value.split()).strip().rstrip(".")
    text = re.sub(r"^(?:Human review required|Policy evaluation found a mismatch):\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"could not be verified from extracted data",
        "could not be confirmed in the uploaded document",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"Required extracted value\(s\) are unavailable:\s*",
        "The document does not clearly show ",
        text,
        flags=re.IGNORECASE,
    )
    return text[:350]


def _needs_tax_declaration_guidance(findings: list[dict]) -> bool:
    text = " ".join(
        str(value)
        for finding in findings
        for value in (
            finding.get("message", ""),
            finding.get("assessment_reason", ""),
            *finding.get("missing_fields", []),
        )
    ).casefold()
    return (
        "not-registered declaration" in text
        or "not registered declaration" in text
        or "declaration date and signatory when not registered" in text
    )


def _fallback_flag_reason(requirement: RequiredDocument, findings: list[dict]) -> str:
    label = requirement.label
    missing = sorted({
        field
        for finding in findings
        for field in finding.get("missing_fields", [])
        if isinstance(field, str)
    })
    disputed = sorted({
        field
        for finding in findings
        for field in finding.get("disputed_fields", [])
        if isinstance(field, str)
    })
    finding_texts = [
        str(finding.get("assessment_reason") or finding.get("message") or "")
        for finding in findings
        if finding.get("assessment_reason") or finding.get("message")
    ]
    combined = " ".join(finding_texts).casefold()

    if _needs_tax_declaration_guidance(findings):
        return (
            "We could not confirm a dated and signed declaration for the supplier's non-GST-registered status. "
            "This declaration records why a GSTIN is not being provided and confirms who made that statement. "
            "Please upload a clear signed tax-status declaration showing the supplier's legal name, that the supplier is not registered for GST, the declaration date, and the authorized signatory's name and signature."
        )

    why = requirement.why.strip().rstrip(".")
    why_sentence = (
        f"This information is needed to {why[:1].lower() + why[1:]}."
        if why
        else "This information is needed to complete the requirement review."
    )
    evidence = requirement.accepted_evidence.strip().rstrip(".") or label
    required_fields = requirement.required_fields.strip().rstrip(".")

    if missing:
        detail = f"We could not confirm {_human_list(missing)} in the uploaded {label.lower()}."
        action = f"Please upload a clear {evidence[:1].lower() + evidence[1:]}"
        if required_fields:
            action += f" showing {required_fields[:1].lower() + required_fields[1:]}"
        action += "."
    elif disputed:
        detail = f"The reviewer could not confirm {_human_list(disputed)} against the uploaded {label.lower()}."
        action = (
            f"Please correct the portal information if it is wrong, or replace the document with "
            f"a {evidence[:1].lower() + evidence[1:]} that shows the correct details."
        )
    elif "does not match" in combined or "mismatch" in combined:
        issue = _plain_finding(finding_texts[0]) if finding_texts else "The document details do not match the portal details"
        detail = f"We found a mismatch in the {label.lower()}: {issue[:1].lower() + issue[1:]}."
        action = (
            "Please correct the portal information if it is wrong, or upload a replacement "
            f"{evidence[:1].lower() + evidence[1:]} with matching details."
        )
    else:
        issue = _plain_finding(finding_texts[0]) if finding_texts else "The document could not be confirmed against the requirement"
        detail = f"We could not complete the {label.lower()} review because {issue[:1].lower() + issue[1:]}."
        action = f"Please upload an updated or clearer {evidence[:1].lower() + evidence[1:]}"
        if required_fields:
            action += f" showing {required_fields[:1].lower() + required_fields[1:]}"
        action += "."
    return f"{detail} {why_sentence} {action}"[:1000]


def _ai_flag_reason_is_usable(
    proposed: str,
    requirement: RequiredDocument,
    findings: list[dict],
) -> bool:
    lower = proposed.casefold()
    banned_phrases = (
        "extracted data",
        "clear evidence or documentation",
        "resolve this issue",
        "requires a verification of",
        "not- registered",
    )
    sentence_count = len(re.findall(r"[.!?](?:\s|$)", proposed))
    if not 25 <= len(proposed.split()) <= 170 or sentence_count != 3:
        return False
    if any(phrase in lower for phrase in banned_phrases):
        return False
    if re.search(r"\b(?:AI|RAG|OCR)\b", proposed, flags=re.IGNORECASE):
        return False
    if not any(
        action in lower
        for action in ("please upload", "please replace", "please correct", "please update")
    ):
        return False
    if _needs_tax_declaration_guidance(findings):
        return all(term in lower for term in ("declaration", "gst", "date")) and any(
            term in lower for term in ("signatory", "signature", "signed")
        )
    return any(
        token in lower
        for token in re.findall(r"[a-z]{4,}", requirement.label.casefold())
    )


@router.get("/{supplier_id}/compliance", response_model=ComplianceRunResponse)
def get_compliance(
    supplier_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ComplianceRunResponse:
    supplier = _get_review_supplier(db, supplier_id)
    return _compliance_response(supplier.compliance_results)


@router.post("/{supplier_id}/compliance/run", response_model=ComplianceRunResponse)
def run_compliance(
    supplier_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ComplianceRunResponse:
    supplier = _get_review_supplier(db, supplier_id)
    _ensure_reviewable(supplier)
    results = persist_compliance_results(db, supplier, evaluate_compliance(supplier))
    db.commit()
    for result in results:
        db.refresh(result)
    record_compliance_checks([result.status.value for result in results])
    return _compliance_response(results)


@router.patch(
    "/{supplier_id}/fields/{field_id}",
    response_model=ExtractedFieldRead,
)
def correct_extracted_field(
    supplier_id: uuid.UUID,
    field_id: uuid.UUID,
    payload: ExtractedFieldUpdate,
    db: Session = Depends(get_db),
) -> ExtractedFieldRead:
    supplier = _get_review_supplier(db, supplier_id)
    _ensure_reviewable(supplier)
    field = db.scalar(
        select(ExtractedField).where(
            ExtractedField.id == field_id,
            ExtractedField.supplier_id == supplier_id,
        )
    )
    if field is None:
        raise HTTPException(status_code=404, detail="Extracted field was not found.")
    source_document = next(
        (document for document in supplier.documents if document.id == field.document_id),
        None,
    )
    if source_document is None or payload.page_number > max(source_document.page_count, 1):
        raise HTTPException(
            status_code=422,
            detail="Page number is outside the source document.",
        )

    previous_value = field.value
    previous_page_number = field.page_number
    previous_confidence = field.confidence
    field.value = payload.value.strip()
    field.page_number = payload.page_number
    field.confidence = 1.0
    field.needs_review = False
    field.review_status = "corrected"
    field.review_comment = "Value corrected and verified by the reviewer."
    field.reviewed_by = payload.reviewer_name.strip()
    field.reviewed_at = datetime.now(UTC)
    supplier.status = SupplierStatus.NEEDS_REVIEW
    db.add(
        AuditEvent(
            supplier_id=supplier_id,
            action="extracted_field.corrected",
            entity_type="extracted_field",
            entity_id=str(field.id),
            details={
                "field_name": field.field_name,
                "source_document_id": str(field.document_id),
                "previous_value": previous_value,
                "corrected_value": field.value,
                "previous_page_number": previous_page_number,
                "page_number": field.page_number,
                "previous_ai_confidence": previous_confidence,
                "reviewer_name": payload.reviewer_name.strip(),
                "compliance_results_invalidated": True,
            },
        )
    )
    persist_compliance_results(db, supplier, evaluate_compliance(supplier))
    db.commit()
    db.refresh(field)
    return ExtractedFieldRead.model_validate(field)


@router.post("/{supplier_id}/fields/review", response_model=list[ExtractedFieldRead])
def review_extracted_fields(
    supplier_id: uuid.UUID,
    payload: ReviewSelectionRequest,
    db: Session = Depends(get_db),
) -> list[ExtractedFieldRead]:
    supplier = _get_review_supplier(db, supplier_id)
    _ensure_reviewable(supplier)
    if payload.action == "dispute" and not (payload.reason or "").strip():
        raise HTTPException(status_code=422, detail="A reason is required when fields are flagged.")
    selected = [field for field in supplier.extracted_fields if field.id in set(payload.ids)]
    if len(selected) != len(set(payload.ids)):
        raise HTTPException(status_code=404, detail="One or more extracted fields were not found.")
    now = datetime.now(UTC)
    for field in selected:
        field.review_status = "verified" if payload.action == "verify" else "disputed"
        field.needs_review = payload.action == "dispute"
        field.review_comment = (payload.reason or "Verified against the source document.").strip()
        field.reviewed_by = payload.reviewer_name.strip()
        field.reviewed_at = now
    event_action = "verified" if payload.action == "verify" else "disputed"
    db.add(AuditEvent(
        supplier_id=supplier_id, action=f"extracted_fields.{event_action}",
        entity_type="extracted_field", entity_id=None,
        details={"field_ids": [str(item.id) for item in selected],
                 "reviewer_name": payload.reviewer_name.strip(), "reason": payload.reason},
    ))
    persist_compliance_results(db, supplier, evaluate_compliance(supplier))
    db.commit()
    return [ExtractedFieldRead.model_validate(item) for item in selected]


@router.post(
    "/{supplier_id}/documents/{document_id}/flag-reason-draft",
    response_model=FlagReasonDraftRead,
)
def draft_flag_reason(
    supplier_id: uuid.UUID,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FlagReasonDraftRead:
    supplier = _get_review_supplier(db, supplier_id)
    _ensure_reviewable(supplier)
    document = next((item for item in supplier.documents if item.id == document_id), None)
    if document is None:
        raise HTTPException(status_code=404, detail="Evidence document was not found.")
    requirement = next(
        (item for item in checklist_for(supplier).documents if item.document_type == document.document_type),
        None,
    )
    label = requirement.label if requirement else document.document_type.value.replace("_", " ").title()
    findings = _flag_findings(supplier, document)
    fallback_requirement = requirement or RequiredDocument(
        document_type=document.document_type,
        label=label,
        why="complete the document review",
        accepted_evidence=label,
    )
    fallback = _fallback_flag_reason(fallback_requirement, findings)
    source = "deterministic_fallback"
    reason = fallback

    if settings.ai_configured and findings:
        query_parts = [label]
        if requirement:
            query_parts.extend([requirement.requirement_id, *requirement.checks])
        try:
            policy_context = policy_context_for(" ".join(query_parts))
            finding_context = json.dumps(
                {
                    "document_label": label,
                    "why_needed": fallback_requirement.why,
                    "accepted_evidence": fallback_requirement.accepted_evidence,
                    "required_information": fallback_requirement.required_fields,
                    "findings": findings,
                    "supplier_facing_resolution_plan": fallback,
                },
                ensure_ascii=True,
            )
            with get_langfuse_tracer().trace(
                name="supplier.reviewer.flag_reason_workflow",
                subject_id=telemetry_subject_id(supplier.id),
                input_data={"document_type": document.document_type.value, "finding_count": len(findings)},
                metadata={
                    "feature": "reviewer_flag_reason",
                    "grounding": "calculated_findings_and_policy_rag",
                },
                tags=["reviewer", "rag", "flag-draft"],
            ) as trace:
                draft = build_openai_service(settings).draft_reviewer_flag_reason(
                    finding_context=finding_context,
                    policy_context=policy_context,
                )
                proposed = " ".join(draft.value.reason.split()).strip()
                repeats_sensitive_value = any(
                    value and value.casefold() in proposed.casefold()
                    for value in (
                        supplier.tax_reference,
                        supplier.bank_account_number,
                        supplier.bank_ifsc,
                    )
                )
                if _ai_flag_reason_is_usable(
                    proposed,
                    fallback_requirement,
                    findings,
                ) and not repeats_sensitive_value and not re.search(
                    r"\[(?:GSTIN|PAN|CIN|EMAIL|PHONE|BANK_ACCOUNT)_\d+\]",
                    proposed,
                ):
                    reason = proposed[:1000]
                    source = "ai_rag"
                trace.update(output={"source": source, "reason_chars": len(reason)})
                trace.score_trace(name="flag_reason_ai_draft_used", value=1 if source == "ai_rag" else 0)
        except Exception:
            # Draft generation is assistive: a grounded deterministic draft keeps the reviewer unblocked.
            source = "deterministic_fallback"
            reason = fallback

    db.add(AuditEvent(
        supplier_id=supplier.id,
        action="reviewer.flag_reason_drafted",
        entity_type="document",
        entity_id=str(document.id),
        details={"source": source, "finding_count": len(findings)},
    ))
    db.commit()
    return FlagReasonDraftRead(reason=reason, source=source, finding_count=len(findings))


@router.post("/{supplier_id}/documents/{document_id}/review", response_model=DocumentRead)
def review_evidence(
    supplier_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: EvidenceReviewRequest,
    db: Session = Depends(get_db),
) -> DocumentRead:
    supplier = _get_review_supplier(db, supplier_id)
    _ensure_reviewable(supplier)
    document = next((item for item in supplier.documents if item.id == document_id), None)
    if document is None:
        raise HTTPException(status_code=404, detail="Evidence document was not found.")
    if payload.action == "dispute" and not (payload.reason or "").strip():
        raise HTTPException(status_code=422, detail="A reason is required when evidence is flagged.")
    reviewer_name = payload.reviewer_name.strip()
    if payload.action == "verify":
        _verify_document(
            db, supplier, document,
            reviewer_name=reviewer_name,
            now=datetime.now(UTC),
        )
    else:
        document.review_status = "disputed"
        document.review_comment = payload.reason.strip() if payload.reason else ""
        document.reviewed_by = reviewer_name
        document.reviewed_at = datetime.now(UTC)
        db.add(AuditEvent(
            supplier_id=supplier_id,
            action="document.disputed",
            entity_type="document",
            entity_id=str(document.id),
            details={
                "reviewer_name": reviewer_name,
                "reason": payload.reason,
                "extracted_field_ids": [],
                "extracted_field_count": 0,
                "compliance_results_recalculated": True,
            },
        ))
    persist_compliance_results(db, supplier, evaluate_compliance(supplier))
    db.commit()
    db.refresh(document)
    return DocumentRead.model_validate(document)


@router.post(
    "/{supplier_id}/requirements/confirm-ready",
    response_model=ConfirmReadyRequirementsResponse,
)
def confirm_ready_requirements(
    supplier_id: uuid.UUID,
    payload: ConfirmReadyRequirementsRequest,
    db: Session = Depends(get_db),
) -> ConfirmReadyRequirementsResponse:
    """Confirm only technically ready requirements with matched policy checks."""
    supplier = _get_review_supplier(db, supplier_id)
    _ensure_reviewable(supplier)
    documents = {document.document_type: document for document in supplier.documents}
    policy_checks = [
        result for result in supplier.compliance_results
        if result.evidence.get("kind") == "policy_check"
    ]
    ready: list[Document] = []
    for requirement in checklist_for(supplier).documents:
        document = documents.get(requirement.document_type)
        checks = [
            result for result in policy_checks
            if result.evidence.get("requirement_id") == requirement.requirement_id
        ]
        checks_matched = bool(checks) and all(
            result.status == ComplianceStatus.PASS
            or result.evidence.get("ai_assessment") in {"matched", "human_verified"}
            for result in checks
        )
        if (
            document is not None
            and document.review_status == "pending"
            and document.processing_status.value == "ready"
            and document.ai_extraction_status == "ready"
            and document.ai_index_status != "failed"
            and document.ocr_quality_status not in {"review", "poor"}
            and not any(
                field.needs_review or field.confidence < 0.75
                for field in supplier.extracted_fields
                if field.document_id == document.id
            )
            and checks_matched
        ):
            ready.append(document)
    if not ready:
        raise HTTPException(
            status_code=409,
            detail="No requirements are currently ready for bulk confirmation.",
        )

    reviewer_name = payload.reviewer_name.strip()
    now = datetime.now(UTC)
    for document in ready:
        _verify_document(
            db, supplier, document,
            reviewer_name=reviewer_name,
            now=now,
            bulk_action=True,
        )
    db.add(AuditEvent(
        supplier_id=supplier.id,
        action="reviewer.ready_requirements.bulk_confirmed",
        entity_type="supplier",
        entity_id=str(supplier.id),
        details={
            "reviewer_name": reviewer_name,
            "document_ids": [str(document.id) for document in ready],
            "confirmed_count": len(ready),
        },
    ))
    persist_compliance_results(db, supplier, evaluate_compliance(supplier))
    db.commit()
    return ConfirmReadyRequirementsResponse(
        confirmed_count=len(ready),
        document_ids=[document.id for document in ready],
    )


@router.post("/{supplier_id}/other-review", response_model=OtherReviewResponse)
def complete_other_review(
    supplier_id: uuid.UUID,
    payload: OtherReviewRequest,
    db: Session = Depends(get_db),
) -> OtherReviewResponse:
    supplier = _get_review_supplier(db, supplier_id)
    _ensure_reviewable(supplier)
    if supplier.category != "OTHER":
        raise HTTPException(status_code=409, detail="This checkpoint applies only to Other-category suppliers.")
    completed_at = datetime.now(UTC)
    supplier.other_review_note = payload.note.strip()
    supplier.other_reviewed_by = payload.reviewer_name.strip()
    supplier.other_review_completed_at = completed_at
    db.add(AuditEvent(
        supplier_id=supplier.id,
        action="supplier.other_policy_legal_review_completed",
        entity_type="supplier",
        entity_id=str(supplier.id),
        details={
            "reviewer_name": supplier.other_reviewed_by,
            "note": supplier.other_review_note,
            "additional_document_count": len(supplier.additional_documents),
        },
    ))
    db.commit()
    return OtherReviewResponse(
        completed_at=completed_at,
        reviewer_name=supplier.other_reviewed_by,
        note=supplier.other_review_note,
    )


@router.post("/{supplier_id}/erp/validate", response_model=ErpValidationResponse)
def validate_erp_record(
    supplier_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ErpValidationResponse:
    supplier = _get_review_supplier(db, supplier_id)
    preview = build_erp_preview(supplier)
    try:
        result = ErpMcpClient().call(db, "validate_supplier_record", {
            "payload": preview.payload,
            "idempotency_key": supplier_idempotency_key(supplier.id),
            "source_supplier_id": str(supplier.id),
        })
    except ErpToolFailure as exc:
        raise HTTPException(status_code=503 if exc.retryable else 409, detail=exc.message) from exc
    return ErpValidationResponse(**result)


@router.get("/{supplier_id}/erp/record", response_model=ErpRecordRead)
def retrieve_erp_record(
    supplier_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ErpRecordRead:
    supplier = _get_review_supplier(db, supplier_id)
    if not supplier.erp_supplier_id:
        raise HTTPException(status_code=404, detail="This supplier does not have an ERP record yet.")
    try:
        result = ErpMcpClient().call(db, "get_supplier_record", {
            "vendor_id": supplier.erp_supplier_id,
            "source_supplier_id": str(supplier.id),
        })
    except ErpToolFailure as exc:
        raise HTTPException(status_code=503 if exc.retryable else 404, detail=exc.message) from exc
    return ErpRecordRead(**result)


@router.post("/{supplier_id}/approve", response_model=DecisionResponse)
def approve_supplier(
    supplier_id: uuid.UUID,
    payload: ApprovalRequest,
    db: Session = Depends(get_db),
) -> DecisionResponse:
    supplier = _get_review_supplier(db, supplier_id)
    if supplier.status == SupplierStatus.REJECTED:
        raise HTTPException(status_code=409, detail="A rejected supplier cannot be approved.")
    if supplier.status == SupplierStatus.APPROVED:
        return DecisionResponse(
            supplier_id=supplier.id,
            status=supplier.status,
            message="Supplier was already approved.",
            erp_supplier_id=supplier.erp_supplier_id,
            erp_record_id=supplier.erp_record_id,
            vendor_id=supplier.vendor_id,
            decided_at=supplier.decided_at or datetime.now(UTC),
        )

    results = persist_compliance_results(db, supplier, evaluate_compliance(supplier))
    record_compliance_checks([result.status.value for result in results])
    if not approval_ready(results):
        db.commit()
        raise HTTPException(
            status_code=409,
            detail="All compliance checks must pass before approval.",
        )
    if supplier.category == "OTHER" and supplier.other_review_completed_at is None:
        db.commit()
        raise HTTPException(
            status_code=409,
            detail="Record the Policy and Legal review outcome before approving an Other-category supplier.",
        )

    preview = build_erp_preview(supplier)
    client = ErpMcpClient()
    try:
        validation = client.call(db, "validate_supplier_record", {
            "payload": preview.payload,
            "idempotency_key": supplier_idempotency_key(supplier.id),
            "source_supplier_id": str(supplier.id),
        })
        if not validation.get("valid"):
            problems = "; ".join(str(item.get("message")) for item in validation.get("errors", []))
            db.commit()
            raise HTTPException(status_code=409, detail=f"ERP validation failed. {problems}")
        erp_result = client.call(db, "create_supplier_record", {
            "payload": preview.payload,
            "idempotency_key": supplier_idempotency_key(supplier.id),
            "source_supplier_id": str(supplier.id),
        })
    except ErpToolFailure as exc:
        db.add(AuditEvent(
            supplier_id=supplier.id, action="erp.supplier.create_failed", entity_type="supplier",
            entity_id=str(supplier.id), details={"code": exc.code, "retryable": exc.retryable},
        ))
        db.commit()
        raise HTTPException(status_code=503 if exc.retryable else 409, detail=exc.message) from exc
    supplier.status = SupplierStatus.APPROVED
    supplier.decision_reason = "Approved after human review."
    supplier.decided_at = datetime.now(UTC)
    supplier.erp_supplier_id = str(erp_result["erp_supplier_id"])
    supplier.erp_record_id = str(erp_result["erp_record_id"])
    supplier.erp_payload = dict(erp_result["payload"])
    db.add(
        AuditEvent(
            supplier_id=supplier.id,
            action="erp.supplier.created",
            entity_type="supplier",
            entity_id=supplier.erp_record_id,
            details={
                "status": erp_result["status"],
                "portal_reference": erp_result.get("supplier_reference"),
                "erp_record_id": supplier.erp_record_id,
                "vendor_id": supplier.vendor_id,
                "payload_fields": sorted(supplier.erp_payload),
                "idempotent_replay": erp_result.get("idempotent_replay", False),
                "transport": "mcp",
            },
        )
    )
    db.add(
        AuditEvent(
            supplier_id=supplier.id,
            action="supplier.approved",
            entity_type="supplier",
            entity_id=str(supplier.id),
            details={
                "reviewer_name": payload.reviewer_name.strip(),
                "erp_supplier_id": supplier.erp_supplier_id,
                "erp_record_id": supplier.erp_record_id,
                "vendor_id": supplier.vendor_id,
            },
        )
    )
    db.commit()
    record_supplier_decision("approved")
    return DecisionResponse(
        supplier_id=supplier.id,
        status=supplier.status,
        message="Supplier approved and sent to the mock ERP approval workflow.",
        erp_supplier_id=supplier.erp_supplier_id,
        erp_record_id=supplier.erp_record_id,
        vendor_id=supplier.vendor_id,
        decided_at=supplier.decided_at,
    )


@router.post("/{supplier_id}/reject", response_model=DecisionResponse)
def reject_supplier(
    supplier_id: uuid.UUID,
    payload: RejectionRequest,
    db: Session = Depends(get_db),
) -> DecisionResponse:
    supplier = _get_review_supplier(db, supplier_id)
    if supplier.status == SupplierStatus.APPROVED:
        raise HTTPException(status_code=409, detail="An approved supplier cannot be rejected.")
    if supplier.status == SupplierStatus.REJECTED:
        return DecisionResponse(
            supplier_id=supplier.id,
            status=supplier.status,
            message="Supplier was already rejected.",
            erp_supplier_id=None,
            erp_record_id=None,
            vendor_id=None,
            decided_at=supplier.decided_at or datetime.now(UTC),
        )

    decided_at = datetime.now(UTC)
    supplier.status = SupplierStatus.REJECTED
    supplier.decision_reason = payload.reason.strip()
    supplier.decided_at = decided_at
    supplier.erp_supplier_id = None
    supplier.erp_record_id = None
    supplier.erp_payload = None
    db.add(
        AuditEvent(
            supplier_id=supplier.id,
            action="supplier.rejected",
            entity_type="supplier",
            entity_id=str(supplier.id),
            details={
                "reason": supplier.decision_reason,
                "reviewer_name": payload.reviewer_name.strip(),
            },
        )
    )
    db.commit()
    record_supplier_decision("rejected")
    return DecisionResponse(
        supplier_id=supplier.id,
        status=supplier.status,
        message="Supplier rejected with an audited reason.",
        erp_supplier_id=None,
        erp_record_id=None,
        vendor_id=None,
        decided_at=decided_at,
    )
