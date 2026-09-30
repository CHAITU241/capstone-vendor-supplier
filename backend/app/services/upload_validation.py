"""Pre-acceptance validation for staged supplier evidence."""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.config import Settings
from app.models import DocumentType, Supplier
from app.services.document_policy import (
    checklist_for,
    extraction_field_names,
    required_extraction_field_names,
    requirement_id_for_document_type,
)
from app.services.documents import ExtractedDocument
from app.services.openai_service import OpenAIService
from app.services.processing import FieldCandidate, normalize_extracted_value
from app.services.redaction import redact_pii
from app.services.tracing import get_langfuse_tracer, telemetry_subject_id


@dataclass(frozen=True)
class UploadValidationIssue:
    code: str
    message: str
    field: str | None = None

    def as_dict(self) -> dict[str, str]:
        result = {"code": self.code, "message": self.message}
        if self.field:
            result["field"] = self.field
        return result


class UploadValidationError(ValueError):
    def __init__(self, issues: list[UploadValidationIssue]):
        self.issues = issues
        super().__init__(" ".join(issue.message for issue in issues))


@dataclass(frozen=True)
class UploadValidationOutcome:
    status: str
    fields: list[FieldCandidate]
    redacted_text: str
    redaction_counts: dict[str, int]
    details: dict
    ocr_quality_score: int | None = None
    ocr_quality_status: str | None = None
    ocr_quality_details: dict | None = None


LEGAL_SUFFIXES = {
    "co", "company", "corp", "corporation", "inc", "incorporated", "llp",
    "limited", "ltd", "pvt", "private", "plc",
}


def _compact(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def _name_key(value: str | None) -> str:
    words = re.findall(r"[a-z0-9]+", (value or "").casefold())
    meaningful = [word for word in words if word not in LEGAL_SUFFIXES]
    return " ".join(meaningful or words)


def names_are_plausibly_same(observed: str, expected: str) -> bool:
    """Reject obvious wrong entities without treating minor OCR noise as identity fraud."""
    observed_key, expected_key = _name_key(observed), _name_key(expected)
    if not observed_key or not expected_key:
        return False
    if observed_key == expected_key:
        return True
    if min(len(observed_key), len(expected_key)) >= 5 and (
        observed_key in expected_key or expected_key in observed_key
    ):
        return True
    observed_tokens, expected_tokens = set(observed_key.split()), set(expected_key.split())
    token_overlap = len(observed_tokens & expected_tokens) / max(
        len(observed_tokens), len(expected_tokens), 1
    )
    similarity = SequenceMatcher(None, observed_key, expected_key).ratio()
    return token_overlap >= 0.75 or similarity >= 0.84


def _field_label(field_name: str) -> str:
    labels = {
        "supplier_name": "supplier/legal name",
        "tax_identifier": "PAN/tax reference",
        "bank_account_number": "bank account number",
        "bank_ifsc": "IFSC",
    }
    return labels.get(field_name, field_name.replace("_", " "))


def _document_label(supplier: Supplier, document_type: DocumentType) -> str:
    return next(
        (
            item.label
            for item in checklist_for(supplier).documents
            if item.document_type == document_type
        ),
        document_type.value.replace("_", " ").title(),
    )


def _quality_status(score: int, settings: Settings) -> str:
    if score < settings.ocr_quality_reject_threshold:
        return "poor"
    if score < settings.ocr_quality_review_threshold:
        return "review"
    return "good"


def _ocr_reliability(
    extracted: ExtractedDocument,
    fields: list[FieldCandidate],
    expected_type: DocumentType,
    settings: Settings,
) -> tuple[int | None, str | None, dict | None]:
    if not extracted.ocr_pages:
        return None, None, None
    visual_score = extracted.ocr_quality_score or 0
    average_confidence = (
        sum(field.confidence for field in fields) / len(fields) * 100
        if fields else 0.0
    )
    required = set(required_extraction_field_names(expected_type))
    found = {field.field_name for field in fields}
    coverage = len(required & found) / max(len(required), 1) * 100
    score = round(
        0.45 * visual_score
        + 0.40 * average_confidence
        + 0.15 * coverage
    )
    score = max(0, min(100, score))
    if visual_score < settings.ocr_quality_reject_threshold:
        score = min(score, max(settings.ocr_quality_reject_threshold - 1, 0))
    elif visual_score < settings.ocr_quality_review_threshold:
        score = min(score, max(settings.ocr_quality_review_threshold - 1, 0))
    return score, _quality_status(score, settings), {
        "meaning": "Estimated OCR extraction reliability; not document authenticity.",
        "visual_quality_score": visual_score,
        "average_field_confidence": round(average_confidence),
        "required_field_coverage": round(coverage),
        "page_metrics": list(extracted.ocr_quality_details),
    }


def _poor_quality_issue(score: int) -> UploadValidationIssue:
    return UploadValidationIssue(
        code="low_ocr_quality",
        message=(
            f"Image quality is too low for reliable OCR (reliability score {score}/100). "
            "Upload a sharper, well-lit image showing the complete document."
        ),
    )


def validate_staged_upload(
    *,
    supplier: Supplier,
    expected_type: DocumentType,
    filename: str,
    extracted: ExtractedDocument,
    settings: Settings,
    ai: OpenAIService | None,
) -> UploadValidationOutcome:
    redaction = redact_pii(extracted.text)
    if not settings.upload_ai_validation_enabled:
        quality_score = extracted.ocr_quality_score
        quality_status = (
            _quality_status(quality_score, settings)
            if quality_score is not None else None
        )
        if quality_score is not None and quality_status == "poor":
            raise UploadValidationError([_poor_quality_issue(quality_score)])
        quality_details = {
            "meaning": "Estimated OCR extraction reliability; not document authenticity.",
            "visual_quality_score": quality_score,
            "page_metrics": list(extracted.ocr_quality_details),
        } if quality_score is not None else None
        return UploadValidationOutcome(
            status="text_only",
            fields=[],
            redacted_text=redaction.text,
            redaction_counts=redaction.counts,
            details={
                "mode": "text_only",
                "text_extraction_method": extracted.text_extraction_method,
                "ocr_pages": list(extracted.ocr_pages),
                "ocr_quality": quality_details,
            },
            ocr_quality_score=quality_score,
            ocr_quality_status=quality_status,
            ocr_quality_details=quality_details,
        )
    if ai is None:
        raise RuntimeError(
            "AI upload validation is unavailable. Configure an AI provider or temporarily "
            "set UPLOAD_AI_VALIDATION_ENABLED=false for offline development."
        )

    tracer = get_langfuse_tracer()
    with tracer.trace(
        name="supplier.document.upload_validation",
        subject_id=telemetry_subject_id(supplier.id),
        input_data={"expected_document_type": expected_type.value, "filename": filename},
        metadata={
            "feature": "upload_validation",
            "expected_document_type": expected_type.value,
            "prompt_version": settings.extraction_prompt_version,
        },
        tags=["supplier", "upload", "validation"],
    ) as trace:
        result = ai.extract_document(
            expected_type=expected_type,
            filename=filename,
            redacted_text=redaction.text,
        )
        extraction = result.value
        issues: list[UploadValidationIssue] = []
        expected_label = _document_label(supplier, expected_type)
        detected_label = _document_label(supplier, extraction.classified_document_type)
        if extraction.classified_document_type != expected_type:
            issues.append(UploadValidationIssue(
                code="wrong_document_type",
                message=(
                    f"Wrong document type: this checklist item expects {expected_label}, "
                    f"but the file appears to be {detected_label}."
                ),
            ))

        allowed = set(extraction_field_names(expected_type))
        best_fields: dict[str, FieldCandidate] = {}
        for field in extraction.fields:
            if field.field_name not in allowed:
                continue
            value = normalize_extracted_value(
                field.value, redaction.replacements, field.field_name,
            )
            if value is None:
                continue
            original_page = field.page_number or 1
            page_number = min(original_page, max(extracted.page_count, 1))
            candidate = FieldCandidate(
                document_id=supplier.id,  # Replaced with the new document id when persisted.
                document_type=expected_type,
                field_name=field.field_name,
                value=value,
                page_number=page_number,
                confidence=field.confidence,
                needs_review=field.confidence < 0.75 or original_page > max(extracted.page_count, 1),
            )
            current = best_fields.get(field.field_name)
            if current is None or candidate.confidence > current.confidence:
                best_fields[field.field_name] = candidate

        quality_score, quality_status, quality_details = _ocr_reliability(
            extracted, list(best_fields.values()), expected_type, settings,
        )
        if quality_score is not None and quality_status == "poor":
            issues.append(_poor_quality_issue(quality_score))
        if quality_status == "review":
            best_fields = {
                name: FieldCandidate(
                    document_id=field.document_id,
                    document_type=field.document_type,
                    field_name=field.field_name,
                    value=field.value,
                    page_number=field.page_number,
                    confidence=field.confidence,
                    needs_review=True,
                )
                for name, field in best_fields.items()
            }

        missing = [
            field_name
            for field_name in required_extraction_field_names(expected_type)
            if field_name not in best_fields
        ]
        if missing:
            labels = ", ".join(_field_label(field_name) for field_name in missing)
            issues.append(UploadValidationIssue(
                code="missing_expected_fields",
                message=f"Expected information could not be found: {labels}.",
            ))

        uncertain_mismatches: list[str] = []
        comparisons = (
            ("supplier_name", supplier.name, names_are_plausibly_same, "supplier_name_mismatch"),
            ("tax_identifier", supplier.tax_reference, lambda a, b: _compact(a) == _compact(b), "tax_reference_mismatch"),
            ("bank_account_number", supplier.bank_account_number, lambda a, b: _compact(a) == _compact(b), "bank_account_mismatch"),
            ("bank_ifsc", supplier.bank_ifsc, lambda a, b: _compact(a) == _compact(b), "ifsc_mismatch"),
        )
        for field_name, expected_value, matcher, code in comparisons:
            observed = best_fields.get(field_name)
            if not observed or not expected_value or matcher(observed.value, expected_value):
                continue
            label = _field_label(field_name)
            if observed.needs_review:
                uncertain_mismatches.append(field_name)
                continue
            issues.append(UploadValidationIssue(
                code=code,
                field=field_name,
                message=(
                    f"{label.capitalize()} mismatch: the value in the file does not match "
                    "the value entered in the portal. Correct the portal details or choose the right file."
                ),
            ))

        requirement_id = requirement_id_for_document_type(expected_type)
        policy_assessments = [
            {
                "requirement_id": requirement_id,
                "check_number": assessment.check_number,
                "result": assessment.result,
                "reason": assessment.reason,
                "evidence_fields": assessment.evidence_fields,
                "page_number": assessment.page_number,
            }
            for assessment in extraction.policy_checks
        ]
        trace.update(output={
            "accepted": not issues,
            "detected_document_type": extraction.classified_document_type.value,
            "issue_codes": [issue.code for issue in issues],
            "field_count": len(best_fields),
            "manual_review_fields": sorted(
                field.field_name for field in best_fields.values() if field.needs_review
            ),
            "uncertain_mismatches": sorted(uncertain_mismatches),
            "ocr_quality_score": quality_score,
            "ocr_quality_status": quality_status,
        })
        trace.score_trace(name="upload_validation_passed", value=0 if issues else 1)
        if issues:
            raise UploadValidationError(issues)
        return UploadValidationOutcome(
            status="passed",
            fields=list(best_fields.values()),
            redacted_text=redaction.text,
            redaction_counts=redaction.counts,
            details={
                "mode": "ai",
                "detected_document_type": extraction.classified_document_type.value,
                "validated_fields": sorted(best_fields),
                "manual_review_fields": sorted(
                    field.field_name for field in best_fields.values() if field.needs_review
                ),
                "uncertain_mismatches": sorted(uncertain_mismatches),
                "policy_assessments": policy_assessments,
                "text_extraction_method": extracted.text_extraction_method,
                "ocr_pages": list(extracted.ocr_pages),
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "model": settings.active_extraction_model,
                "prompt_version": settings.extraction_prompt_version,
                "ocr_quality": quality_details,
            },
            ocr_quality_score=quality_score,
            ocr_quality_status=quality_status,
            ocr_quality_details=quality_details,
        )
