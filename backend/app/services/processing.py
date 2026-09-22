import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass

from chromadb.api.models.Collection import Collection
from openai import APIConnectionError, APIStatusError, AuthenticationError, RateLimitError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.metrics import record_processing, record_rag_question
from app.models import (
    AiRun,
    AiRunStatus,
    AiRunType,
    AuditEvent,
    Document,
    DocumentType,
    ExtractedField,
    Supplier,
    SupplierStatus,
)
from app.services.chunking import chunk_document
from app.services.compliance import evaluate_compliance, persist_compliance_results
from app.services.document_policy import (
    extraction_field_names,
    required_extraction_field_names,
)
from app.services.openai_service import AIResponseError, OpenAIService
from app.services.redaction import redact_pii, restore_placeholders
from app.services.retrieval import (
    RetrievedChunk,
    query_supplier_chunks,
    replace_document_chunks,
)

NOT_FOUND_ANSWER = "Information not found in uploaded supplier documents."
NULL_LIKE_VALUES = {
    "",
    "-",
    "n/a",
    "na",
    "none",
    "not applicable",
    "not available",
    "not provided",
    "null",
    "unknown",
}

FIELD_SOURCE_PRIORITY: dict[str, tuple[DocumentType, ...]] = {
    "supplier_name": (DocumentType.REGISTRATION, DocumentType.TAX, DocumentType.INSURANCE),
    "address": (DocumentType.REGISTRATION, DocumentType.TAX, DocumentType.INSURANCE),
    "country": (DocumentType.REGISTRATION, DocumentType.TAX, DocumentType.INSURANCE),
    "tax_identifier": (DocumentType.TAX, DocumentType.REGISTRATION, DocumentType.INSURANCE),
    "contact_name": (DocumentType.REGISTRATION, DocumentType.TAX, DocumentType.INSURANCE),
    "contact_email": (DocumentType.REGISTRATION, DocumentType.TAX, DocumentType.INSURANCE),
    "insurance_provider": (DocumentType.INSURANCE, DocumentType.REGISTRATION, DocumentType.TAX),
    "insurance_expiry_date": (DocumentType.INSURANCE, DocumentType.REGISTRATION, DocumentType.TAX),
    "payment_terms": (DocumentType.REGISTRATION, DocumentType.TAX, DocumentType.INSURANCE),
}


def _safe_failure_message(
    exc: Exception,
    *,
    stage: str | None = None,
    document_name: str | None = None,
) -> str:
    """Return an operational error without persisting secrets or document content."""
    if isinstance(exc, AuthenticationError):
        reason = "The AI provider rejected authentication. Check the configured API key."
    elif isinstance(exc, RateLimitError):
        reason = "The AI provider rate limit or credit quota was exceeded."
    elif isinstance(exc, APIConnectionError):
        reason = "The AI provider could not be reached. Check the provider endpoint and VM network."
    elif isinstance(exc, APIStatusError):
        reason = f"The AI provider request failed with HTTP {exc.status_code}."
    elif isinstance(exc, AIResponseError):
        reason = str(exc)
    elif type(exc).__name__ == "LengthFinishReasonError":
        reason = (
            "The extraction model exhausted its output allowance before completing "
            "the structured result. The response was discarded; no partial fields were saved."
        )
    else:
        reason = f"{type(exc).__name__}: the AI run failed."
    location = stage or "AI processing"
    if document_name:
        location += f" for {document_name}"
    return f"{location} failed. {reason}"


@dataclass(frozen=True)
class ProcessingOutcome:
    run: AiRun
    field_count: int
    chunk_count: int
    redaction_counts: dict[str, int]
    processed_document_count: int = 0
    failed_document_count: int = 0


@dataclass(frozen=True)
class QuestionOutcome:
    answer: str
    information_found: bool
    citations: list[RetrievedChunk]
    run: AiRun


@dataclass(frozen=True)
class FieldCandidate:
    document_id: uuid.UUID
    document_type: DocumentType
    field_name: str
    value: str
    page_number: int
    confidence: float
    needs_review: bool


def normalize_extracted_value(
    value: str | None,
    replacements: dict[str, str],
) -> str | None:
    if value is None:
        return None
    restored = restore_placeholders(value, replacements).strip()
    null_check = restored.strip("\"'").strip().casefold().rstrip(".")
    return None if null_check in NULL_LIKE_VALUES else restored


def comparison_key(field_name: str, value: str) -> str:
    """Normalize presentation differences before checking cross-document conflicts."""
    normalized = " ".join(value.casefold().split())
    if field_name in {"supplier_name", "contact_name", "insurance_provider"}:
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return normalized.strip()


def select_canonical_fields(
    candidates: list[FieldCandidate],
) -> tuple[list[FieldCandidate], list[str]]:
    grouped: dict[str, list[FieldCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.field_name].append(candidate)

    selected: list[FieldCandidate] = []
    conflicts: list[str] = []
    for field_name, field_candidates in grouped.items():
        priorities = FIELD_SOURCE_PRIORITY.get(field_name, tuple(DocumentType))

        def rank(candidate: FieldCandidate) -> tuple[int, bool, float]:
            try:
                source_rank = len(priorities) - priorities.index(candidate.document_type)
            except ValueError:
                source_rank = 0
            return source_rank, not candidate.needs_review, candidate.confidence

        # A registration form's primary contact is not the same business role
        # as a tax certificate's authorized signatory or an insurance
        # certificate's representative. Compare contact names only within the
        # primary-contact source when it is available.
        comparable_candidates = field_candidates
        if field_name == "contact_name":
            registration_candidates = [
                candidate
                for candidate in field_candidates
                if candidate.document_type == DocumentType.REGISTRATION
            ]
            if registration_candidates:
                comparable_candidates = registration_candidates

        chosen = max(comparable_candidates, key=rank)
        distinct_values = {
            comparison_key(field_name, candidate.value)
            for candidate in comparable_candidates
        }
        has_conflict = len(distinct_values) > 1
        if has_conflict:
            conflicts.append(field_name)
            chosen = FieldCandidate(
                document_id=chosen.document_id,
                document_type=chosen.document_type,
                field_name=chosen.field_name,
                value=chosen.value,
                page_number=chosen.page_number,
                confidence=chosen.confidence,
                needs_review=True,
            )
        selected.append(chosen)

    return sorted(selected, key=lambda item: item.field_name), sorted(conflicts)


def _start_run(
    db: Session,
    supplier: Supplier,
    run_type: AiRunType,
    model: str,
    prompt_version: str,
) -> AiRun:
    run = AiRun(
        supplier_id=supplier.id,
        run_type=run_type,
        status=AiRunStatus.PROCESSING,
        model=model,
        prompt_version=prompt_version,
        details={},
    )
    db.add(run)
    db.flush()
    db.add(
        AuditEvent(
            supplier_id=supplier.id,
            action=f"ai.{run_type.value}.started",
            entity_type="ai_run",
            entity_id=str(run.id),
            details={"model": model, "prompt_version": prompt_version},
        )
    )
    db.commit()
    db.refresh(run)
    return run


def _fail_run(
    db: Session,
    supplier_id: uuid.UUID,
    run_id: uuid.UUID,
    message: str,
    latency_ms: int,
) -> None:
    db.rollback()
    run = db.get(AiRun, run_id)
    supplier = db.get(Supplier, supplier_id)
    if run is not None:
        run.status = AiRunStatus.FAILED
        run.error_message = message[:500]
        run.latency_ms = latency_ms
    if supplier is not None:
        supplier.status = SupplierStatus.NEEDS_REVIEW
    db.add(
        AuditEvent(
            supplier_id=supplier_id,
            action="ai.run.failed",
            entity_type="ai_run",
            entity_id=str(run_id),
            details={"reason": message[:500]},
        )
    )
    db.commit()


def _process_supplier_documents(
    db: Session,
    supplier: Supplier,
    settings: Settings,
    ai: OpenAIService,
    collection: Collection,
    document_ids: set[uuid.UUID] | None = None,
) -> ProcessingOutcome:
    run = _start_run(
        db,
        supplier,
        AiRunType.PROCESSING,
        settings.active_extraction_model,
        settings.extraction_prompt_version,
    )
    started = time.perf_counter()
    input_tokens = 0
    output_tokens = 0
    chunk_count = 0
    redaction_counts: dict[str, int] = {}
    classification_mismatches: list[str] = []
    failed_documents: list[dict[str, str]] = []
    processed_document_ids: set[uuid.UUID] = set()

    supplier.status = SupplierStatus.PROCESSING
    supplier.decision_reason = None
    supplier.decided_at = None
    supplier.erp_supplier_id = None
    supplier.erp_payload = None
    db.commit()

    documents = [
        document for document in sorted(supplier.documents, key=lambda item: item.document_type.value)
        if document_ids is None or document.id in document_ids
    ]
    if document_ids is None:
        documents = [
            document for document in documents
            if document.ai_extraction_status != "ready" or document.ai_index_status != "ready"
        ]

    for document in documents:
        processed_document_ids.add(document.id)
        redaction = redact_pii(document.extracted_text or "")
        document.redacted_text = redaction.text
        document.redaction_summary = redaction.counts
        for category, count in redaction.counts.items():
            redaction_counts[category] = redaction_counts.get(category, 0) + count
        db.commit()

        if document.ai_index_status != "ready":
            document.ai_index_status = "processing"
            document.ai_index_error = None
            db.commit()
            try:
                chunks = chunk_document(
                    redaction.text,
                    model=settings.active_embedding_model,
                    chunk_size=settings.chunk_size_tokens,
                    overlap=settings.chunk_overlap_tokens,
                )
                embedding = ai.embed([chunk.text for chunk in chunks])
                input_tokens += embedding.input_tokens
                replace_document_chunks(
                    collection=collection,
                    supplier_id=str(supplier.id),
                    document_id=str(document.id),
                    filename=document.filename,
                    chunks=chunks,
                    embeddings=embedding.embeddings,
                )
                chunk_count += len(chunks)
                document.ai_index_status = "ready"
                document.ai_index_error = None
                db.commit()
            except Exception as exc:
                db.rollback()
                document = db.get(Document, document.id)
                message = _safe_failure_message(
                    exc, stage="Search indexing", document_name=document.filename,
                )
                document.ai_index_status = "failed"
                document.ai_index_error = message[:500]
                failed_documents.append({"document_id": str(document.id), "filename": document.filename,
                                         "stage": "indexing", "message": message})
                db.add(AuditEvent(
                    supplier_id=supplier.id,
                    action="ai.document.failed",
                    entity_type="document",
                    entity_id=str(document.id),
                    details={"stage": "indexing", "reason": message[:500]},
                ))
                db.commit()

        if document.ai_extraction_status != "ready":
            document.ai_extraction_status = "processing"
            document.ai_extraction_error = None
            db.commit()
            try:
                extraction = ai.extract_document(
                    expected_type=document.document_type,
                    filename=document.filename,
                    redacted_text=redaction.text,
                )
                input_tokens += extraction.input_tokens
                output_tokens += extraction.output_tokens
                type_mismatch = extraction.value.classified_document_type != document.document_type
                if type_mismatch:
                    classification_mismatches.append(document.filename)
                    document.review_status = "attention"
                    document.review_comment = "AI classified this file differently from its selected requirement."
                elif document.review_status not in {"verified", "disputed"}:
                    document.review_status = "pending"
                    document.review_comment = None

                allowed_fields = set(extraction_field_names(document.document_type))
                best_fields = {}
                for field in extraction.value.fields:
                    if field.field_name not in allowed_fields:
                        continue
                    value = normalize_extracted_value(field.value, redaction.replacements)
                    if value is None:
                        continue
                    page_number = field.page_number or 1
                    page_out_of_range = page_number > max(document.page_count, 1)
                    page_number = min(page_number, max(document.page_count, 1))
                    candidate = FieldCandidate(
                        document_id=document.id,
                        document_type=document.document_type,
                        field_name=field.field_name,
                        value=value,
                        page_number=page_number,
                        confidence=field.confidence,
                        needs_review=field.confidence < 0.75 or type_mismatch or page_out_of_range,
                    )
                    existing = best_fields.get(field.field_name)
                    if existing is None or candidate.confidence > existing.confidence:
                        best_fields[field.field_name] = candidate

                db.execute(delete(ExtractedField).where(ExtractedField.document_id == document.id))
                for field in best_fields.values():
                    db.add(ExtractedField(
                        supplier_id=supplier.id,
                        document_id=field.document_id,
                        field_name=field.field_name,
                        value=field.value,
                        page_number=field.page_number,
                        confidence=field.confidence,
                        needs_review=field.needs_review,
                        review_status="attention" if field.needs_review else "pending",
                    ))
                document.ai_extraction_status = "ready"
                document.ai_extraction_error = None
                db.commit()
            except Exception as exc:
                db.rollback()
                document = db.get(Document, document.id)
                message = _safe_failure_message(
                    exc, stage="Document extraction", document_name=document.filename,
                )
                document.ai_extraction_status = "failed"
                document.ai_extraction_error = message[:500]
                failed_documents.append({"document_id": str(document.id), "filename": document.filename,
                                         "stage": "extraction", "message": message})
                db.add(AuditEvent(
                    supplier_id=supplier.id,
                    action="ai.document.failed",
                    entity_type="document",
                    entity_id=str(document.id),
                    details={"stage": "extraction", "reason": message[:500]},
                ))
                db.commit()

    all_documents = db.scalars(select(Document).where(Document.supplier_id == supplier.id)).all()
    all_fields = db.scalars(select(ExtractedField).where(ExtractedField.supplier_id == supplier.id)).all()
    recorded_failures = {
        (item["document_id"], item["stage"]) for item in failed_documents
    }
    for document in all_documents:
        for stage, status, message in (
            ("extraction", document.ai_extraction_status, document.ai_extraction_error),
            ("indexing", document.ai_index_status, document.ai_index_error),
        ):
            key = (str(document.id), stage)
            if status == "failed" and key not in recorded_failures:
                failed_documents.append({
                    "document_id": str(document.id),
                    "filename": document.filename,
                    "stage": stage,
                    "message": message or f"{stage.title()} failed for {document.filename}.",
                })
                recorded_failures.add(key)
    document_types = {document.id: document.document_type for document in all_documents}
    conflict_candidates = [
        FieldCandidate(field.document_id, document_types[field.document_id], field.field_name,
                       field.value, field.page_number, field.confidence, field.needs_review)
        for field in all_fields if field.field_name in FIELD_SOURCE_PRIORITY
    ]
    _, field_conflicts = select_canonical_fields(conflict_candidates)

    run.input_tokens = input_tokens
    run.output_tokens = output_tokens
    run.latency_ms = int((time.perf_counter() - started) * 1000)
    run.retrieval_count = chunk_count
    failed_document_ids = {item["document_id"] for item in failed_documents}
    missing_required_fields = []
    fields_by_document: dict[uuid.UUID, set[str]] = defaultdict(set)
    for field in all_fields:
        fields_by_document[field.document_id].add(field.field_name)
    for document in all_documents:
        missing = sorted(
            set(required_extraction_field_names(document.document_type))
            - fields_by_document[document.id]
        )
        if missing and document.ai_extraction_status == "ready":
            missing_required_fields.append({
                "document_id": str(document.id),
                "filename": document.filename,
                "fields": missing,
            })

    run.status = AiRunStatus.FAILED if failed_documents else AiRunStatus.SUCCEEDED
    run.error_message = (
        f"{len(failed_documents)} document stage(s) failed; successful documents were retained. Retry only the failed evidence."
        if failed_documents else None
    )
    run.details = {
        "ai_provider": settings.ai_provider,
        "embedding_model": settings.active_embedding_model,
        "chunk_size_tokens": settings.chunk_size_tokens,
        "chunk_overlap_tokens": settings.chunk_overlap_tokens,
        "redaction_counts": redaction_counts,
        "classification_mismatches": classification_mismatches,
        "field_conflicts": field_conflicts,
        "failed_documents": failed_documents,
        "missing_required_fields": missing_required_fields,
        "processed_document_ids": [str(item) for item in sorted(processed_document_ids, key=str)],
        "ready_extractions": sum(document.ai_extraction_status == "ready" for document in all_documents),
        "ready_indexes": sum(document.ai_index_status == "ready" for document in all_documents),
        "total_documents": len(all_documents),
    }
    supplier = db.get(Supplier, supplier.id)
    supplier.status = SupplierStatus.NEEDS_REVIEW
    db.add(AuditEvent(
        supplier_id=supplier.id,
        action="ai.processing.partial" if failed_documents else "ai.processing.completed",
        entity_type="ai_run",
        entity_id=str(run.id),
        details={"field_count": len(all_fields), "chunk_count": chunk_count,
                 "failed_document_count": len(failed_document_ids)},
    ))
    db.commit()
    db.refresh(run)
    db.refresh(supplier)
    db.expire(supplier, ["documents", "extracted_fields", "compliance_results"])
    persist_compliance_results(db, supplier, evaluate_compliance(supplier))
    db.commit()
    record_processing("partial" if failed_documents else "success")
    return ProcessingOutcome(
        run=run,
        field_count=len(all_fields),
        chunk_count=chunk_count,
        redaction_counts=redaction_counts,
        processed_document_count=len(processed_document_ids),
        failed_document_count=len(failed_document_ids),
    )


def process_supplier_documents(
    db: Session,
    supplier: Supplier,
    settings: Settings,
    ai: OpenAIService,
    collection: Collection,
    document_ids: set[uuid.UUID] | None = None,
) -> ProcessingOutcome:
    """Process evidence independently while still closing unexpected run failures."""
    supplier_id = supplier.id
    try:
        return _process_supplier_documents(
            db=db,
            supplier=supplier,
            settings=settings,
            ai=ai,
            collection=collection,
            document_ids=document_ids,
        )
    except Exception as exc:
        db.rollback()
        failed_run = db.scalar(
            select(AiRun)
            .where(
                AiRun.supplier_id == supplier_id,
                AiRun.run_type == AiRunType.PROCESSING,
                AiRun.status == AiRunStatus.PROCESSING,
            )
            .order_by(AiRun.created_at.desc())
        )
        if failed_run is not None:
            _fail_run(
                db,
                supplier_id,
                failed_run.id,
                _safe_failure_message(exc, stage="Processing finalization"),
                0,
            )
        record_processing("error")
        raise


def answer_supplier_question(
    db: Session,
    supplier: Supplier,
    question: str,
    settings: Settings,
    ai: OpenAIService,
    collection: Collection,
) -> QuestionOutcome:
    run = _start_run(
        db,
        supplier,
        AiRunType.QUESTION,
        settings.active_answer_model,
        settings.answer_prompt_version,
    )
    started = time.perf_counter()
    try:
        redaction = redact_pii(question.strip())
        query_embedding = ai.embed([redaction.text])
        retrieved = query_supplier_chunks(
            collection=collection,
            supplier_id=str(supplier.id),
            query_embedding=query_embedding.embeddings[0],
            limit=settings.rag_top_k,
            max_distance=settings.rag_max_distance,
        )
        input_tokens = query_embedding.input_tokens
        output_tokens = 0

        if not retrieved:
            answer = NOT_FOUND_ANSWER
            information_found = False
            citations: list[RetrievedChunk] = []
        else:
            evidence_by_label = {
                f"chunk_{index}": chunk
                for index, chunk in enumerate(retrieved, start=1)
            }
            evidence = "\n\n".join(
                (
                    f"[Chunk {label}]\n"
                    f"Source: {chunk.filename}, page {chunk.page_number}\n"
                    f"{chunk.text}"
                )
                for label, chunk in evidence_by_label.items()
            )
            model_result = ai.answer_question(redaction.text, evidence)
            input_tokens += model_result.input_tokens
            output_tokens += model_result.output_tokens
            cited_labels = [
                label
                for label in model_result.value.cited_chunk_ids
                if label in evidence_by_label
            ]
            information_found = (
                model_result.value.information_found and bool(cited_labels)
            )
            answer = model_result.value.answer if information_found else NOT_FOUND_ANSWER
            citations = (
                [evidence_by_label[label] for label in cited_labels]
                if information_found
                else []
            )

        run.status = AiRunStatus.SUCCEEDED
        run.input_tokens = input_tokens
        run.output_tokens = output_tokens
        run.latency_ms = int((time.perf_counter() - started) * 1000)
        run.retrieval_count = len(retrieved)
        run.details = {
            "ai_provider": settings.ai_provider,
            "embedding_model": settings.active_embedding_model,
            "retrieved_chunk_ids": [chunk.chunk_id for chunk in retrieved],
            "retrieval_distances": [round(chunk.distance, 4) for chunk in retrieved],
            "redaction_counts": redaction.counts,
            "information_found": information_found,
            "model_information_found": (
                model_result.value.information_found if retrieved else False
            ),
            "model_cited_labels": (
                model_result.value.cited_chunk_ids if retrieved else []
            ),
        }
        db.add(
            AuditEvent(
                supplier_id=supplier.id,
                action="ai.question.answered",
                entity_type="ai_run",
                entity_id=str(run.id),
                details={
                    "information_found": information_found,
                    "citation_count": len(citations),
                },
            )
        )
        db.commit()
        db.refresh(run)
        record_rag_question(information_found, len(retrieved))
        return QuestionOutcome(
            answer=answer,
            information_found=information_found,
            citations=citations,
            run=run,
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _fail_run(db, supplier.id, run.id, _safe_failure_message(exc), latency_ms)
        raise
