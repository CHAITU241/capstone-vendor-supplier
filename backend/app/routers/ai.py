import uuid
import time

from fastapi import APIRouter, Depends, HTTPException, Response
from app.services.portal_auth import require_reviewer
from app.services.document_policy import required_types_for
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.database import get_db
from app.models import AiRun, AiRunStatus, AiRunType, ProcessingStatus, Supplier, SupplierStatus
from app.schemas import (
    AssistantHistoryMessage,
    AiRunRead,
    GeneralAssistantMessage,
    GeneralAssistantRequest,
    GeneralAssistantResponse,
    GeneralAssistantRun,
    ProcessSupplierResponse,
    QuestionCitation,
    SupplierQuestionRequest,
    SupplierQuestionResponse,
)
from app.services.openai_service import (
    AIConfigurationError,
    get_openai_service,
)
from app.services.processing import (
    answer_supplier_question,
    process_supplier_documents,
)
from app.services.retrieval import get_chunk_collection
from app.services.retrieval import query_supplier_chunks
from app.services.assistant_history import clear_history, conversation_history, save_exchange
from app.services.assistant_scope import is_reviewer_case_question
from app.services.policy_retrieval import policy_context_for, reviewer_context_for
from app.services.redaction import redact_pii
from app.services.tracing import get_langfuse_tracer, telemetry_subject_id

router = APIRouter(prefix="/suppliers", tags=["ai"], dependencies=[Depends(require_reviewer)])


def _get_supplier_with_documents(db: Session, supplier_id: uuid.UUID) -> Supplier:
    supplier = db.scalar(
        select(Supplier)
        .where(Supplier.id == supplier_id)
        .options(
            selectinload(Supplier.documents),
            selectinload(Supplier.extracted_fields),
            selectinload(Supplier.compliance_results),
            selectinload(Supplier.ai_runs),
        )
    )
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier was not found.")
    return supplier


def _get_ai_service():
    try:
        return get_openai_service()
    except AIConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{supplier_id}/process", response_model=ProcessSupplierResponse)
def process_supplier(
    supplier_id: uuid.UUID,
    refresh: bool = False,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProcessSupplierResponse:
    supplier = _get_supplier_with_documents(db, supplier_id)
    if supplier.status in {SupplierStatus.APPROVED, SupplierStatus.REJECTED}:
        raise HTTPException(
            status_code=409,
            detail="A finalized supplier cannot be reprocessed in this demo workflow.",
        )
    required_types = required_types_for(supplier)
    ready_types = {
        document.document_type
        for document in supplier.documents
        if document.processing_status == ProcessingStatus.READY
        and document.extracted_text
    }
    missing = sorted(item.value for item in required_types - ready_types)
    if missing:
        raise HTTPException(
            status_code=409,
            detail=f"Ready documents are required for: {', '.join(missing)}.",
        )

    try:
        outcome = process_supplier_documents(
            db=db,
            supplier=supplier,
            settings=settings,
            ai=_get_ai_service(),
            collection=get_chunk_collection(),
            force_reprocess=refresh,
        )
    except HTTPException:
        raise
    except Exception as exc:
        failed_run = db.scalar(
            select(AiRun).where(
                AiRun.supplier_id == supplier_id,
                AiRun.run_type == AiRunType.PROCESSING,
                AiRun.status == AiRunStatus.FAILED,
            ).order_by(AiRun.created_at.desc())
        )
        raise HTTPException(
            status_code=502,
            detail=(failed_run.error_message if failed_run and failed_run.error_message
                    else "AI processing failed before a diagnostic could be recorded."),
        ) from exc

    return ProcessSupplierResponse(
        run=AiRunRead.model_validate(outcome.run),
        field_count=outcome.field_count,
        chunk_count=outcome.chunk_count,
        redaction_counts=outcome.redaction_counts,
        processed_document_count=outcome.processed_document_count,
        failed_document_count=outcome.failed_document_count,
    )


@router.get("/{supplier_id}/assistant/history", response_model=list[AssistantHistoryMessage])
def reviewer_assistant_history(
    supplier_id: uuid.UUID, db: Session = Depends(get_db),
) -> list[AssistantHistoryMessage]:
    supplier = _get_supplier_with_documents(db, supplier_id)
    return [AssistantHistoryMessage.model_validate(item) for item in conversation_history(db, supplier.id, "reviewer", limit=50)]


@router.delete("/{supplier_id}/assistant/history", status_code=204)
def clear_reviewer_assistant_history(
    supplier_id: uuid.UUID, db: Session = Depends(get_db),
) -> Response:
    supplier = _get_supplier_with_documents(db, supplier_id)
    clear_history(db, supplier.id, "reviewer")
    return Response(status_code=204)


@router.post("/{supplier_id}/assistant", response_model=GeneralAssistantResponse)
def ask_reviewer_assistant(
    supplier_id: uuid.UUID,
    payload: GeneralAssistantRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GeneralAssistantResponse:
    if payload.messages[-1].role != "user":
        raise HTTPException(status_code=422, detail="The last message must be a user question.")
    question = payload.messages[-1].content.strip()
    if len(question) < 3:
        raise HTTPException(status_code=422, detail="Enter a question with at least three characters.")
    supplier = _get_supplier_with_documents(db, supplier_id)
    prior = conversation_history(db, supplier.id, "reviewer")
    messages = [
        GeneralAssistantMessage(role=item.role, content=item.content)
        for item in prior
    ] + [GeneralAssistantMessage(role="user", content=question)]
    while len(messages) > 12 or (len(messages) > 1 and sum(len(item.content) for item in messages) > 10000):
        messages.pop(0)

    if not is_reviewer_case_question(question, [item.content for item in messages[:-1] if item.role == "user"]):
        answer = "I can only help with this supplier’s onboarding case, evidence, extracted values, policy checks, and review workflow."
        response = GeneralAssistantResponse(
            answer=answer,
            run=GeneralAssistantRun(
                model="scope-check", prompt_version="reviewer-assistant-v1",
                input_tokens=0, output_tokens=0, latency_ms=0, redaction_counts={},
            ),
        )
        save_exchange(db, supplier.id, "reviewer", question, answer)
        return response

    ai = _get_ai_service()
    collection = get_chunk_collection()
    retrieved = []
    indexed = collection.get(where={"supplier_id": str(supplier.id)}, limit=1)
    input_tokens = 0
    if indexed.get("ids"):
        query_redaction = redact_pii(question)
        embedding = ai.embed([query_redaction.text])
        input_tokens += embedding.input_tokens
        retrieved = query_supplier_chunks(
            collection=collection,
            supplier_id=str(supplier.id),
            query_embedding=embedding.embeddings[0],
            limit=settings.rag_top_k,
            max_distance=settings.rag_max_distance,
        )

    evidence_by_label = {
        f"chunk_{index}": chunk
        for index, chunk in enumerate(retrieved, start=1)
    }
    context_parts = [reviewer_context_for(supplier), policy_context_for(question)]
    if retrieved:
        context_parts.append("RELEVANT UPLOADED-DOCUMENT EXCERPTS:")
        context_parts.extend(
            f"[Chunk {label}]\nSource: {chunk.filename}, page {chunk.page_number}\n{chunk.text}"
            for label, chunk in evidence_by_label.items()
        )
    context_redaction = redact_pii("\n\n".join(context_parts))
    redaction_counts = dict(context_redaction.counts)
    sanitized_messages = []
    for message in messages:
        redaction = redact_pii(message.content)
        sanitized_messages.append({"role": message.role, "content": redaction.text})
        for category, count in redaction.counts.items():
            redaction_counts[category] = redaction_counts.get(category, 0) + count

    started = time.perf_counter()
    try:
        with get_langfuse_tracer().trace(
            name="reviewer.assistant.conversation",
            input_data={"message_count": len(sanitized_messages), "question_chars": len(question)},
            metadata={
                "feature": "reviewer_assistant",
                "provider": settings.ai_provider,
                "model": settings.active_answer_model,
                "embedding_model": settings.active_embedding_model,
                "prompt_version": "reviewer-assistant-v1",
                "retrieval_count": len(retrieved),
            },
            subject_id=telemetry_subject_id(supplier.id),
            session_id=f"{telemetry_subject_id(supplier.id)}-reviewer-assistant",
            tags=["assistant", "reviewer", settings.ai_provider],
        ) as trace:
            result = ai.answer_reviewer_question(sanitized_messages, context_redaction.text)
            valid_citations = sum(
                label in evidence_by_label for label in result.value.cited_chunk_ids
            )
            trace.update(output={
                "answer_chars": len(result.value.answer),
                "retrieval_count": len(retrieved),
                "citation_count": valid_citations,
                "redaction_count": sum(redaction_counts.values()),
            })
            trace.score_trace(
                name="citation_guard",
                value=1 if not retrieved or valid_citations > 0 else 0,
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="The reviewer assistant could not answer this question.") from exc

    cited_labels = [
        label for label in result.value.cited_chunk_ids
        if label in evidence_by_label
    ]
    citations = [
        QuestionCitation(
            chunk_id=chunk.chunk_id,
            filename=chunk.filename,
            page_number=chunk.page_number,
            excerpt=chunk.text[:280],
        )
        for chunk in (evidence_by_label[label] for label in cited_labels)
    ]
    response = GeneralAssistantResponse(
        answer=result.value.answer,
        citations=citations,
        run=GeneralAssistantRun(
            model=settings.active_answer_model,
            prompt_version="reviewer-assistant-v1",
            input_tokens=input_tokens + result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
            redaction_counts=redaction_counts,
        ),
    )
    save_exchange(
        db, supplier.id, "reviewer", question, response.answer,
        [citation.model_dump(mode="json") for citation in citations],
    )
    return response


@router.post("/{supplier_id}/documents/{document_id}/process", response_model=ProcessSupplierResponse)
def process_one_supplier_document(
    supplier_id: uuid.UUID,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProcessSupplierResponse:
    supplier = _get_supplier_with_documents(db, supplier_id)
    if supplier.status in {SupplierStatus.APPROVED, SupplierStatus.REJECTED}:
        raise HTTPException(status_code=409, detail="A finalized supplier cannot be reprocessed.")
    document = next((item for item in supplier.documents if item.id == document_id), None)
    if document is None:
        raise HTTPException(status_code=404, detail="Document was not found for this supplier.")
    if document.processing_status != ProcessingStatus.READY or not document.extracted_text:
        raise HTTPException(status_code=409, detail="The document is not ready for AI processing.")

    outcome = process_supplier_documents(
        db=db,
        supplier=supplier,
        settings=settings,
        ai=_get_ai_service(),
        collection=get_chunk_collection(),
        document_ids={document.id},
    )
    return ProcessSupplierResponse(
        run=AiRunRead.model_validate(outcome.run),
        field_count=outcome.field_count,
        chunk_count=outcome.chunk_count,
        redaction_counts=outcome.redaction_counts,
        processed_document_count=outcome.processed_document_count,
        failed_document_count=outcome.failed_document_count,
    )


@router.post("/{supplier_id}/questions", response_model=SupplierQuestionResponse)
def ask_supplier_question(
    supplier_id: uuid.UUID,
    payload: SupplierQuestionRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SupplierQuestionResponse:
    supplier = _get_supplier_with_documents(db, supplier_id)
    collection = get_chunk_collection()
    indexed = collection.get(where={"supplier_id": str(supplier.id)}, limit=1)
    if not indexed.get("ids"):
        raise HTTPException(
            status_code=409,
            detail="Process the supplier documents before asking questions.",
        )

    try:
        outcome = answer_supplier_question(
            db=db,
            supplier=supplier,
            question=payload.question,
            settings=settings,
            ai=_get_ai_service(),
            collection=collection,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="The supplier question could not be answered.",
        ) from exc

    return SupplierQuestionResponse(
        answer=outcome.answer,
        information_found=outcome.information_found,
        citations=[
            QuestionCitation(
                chunk_id=chunk.chunk_id,
                filename=chunk.filename,
                page_number=chunk.page_number,
                excerpt=chunk.text[:280],
            )
            for chunk in outcome.citations
        ],
        run=AiRunRead.model_validate(outcome.run),
    )
