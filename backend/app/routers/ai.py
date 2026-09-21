import uuid

from fastapi import APIRouter, Depends, HTTPException
from app.services.portal_auth import require_reviewer
from app.services.document_policy import required_types_for
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.database import get_db
from app.models import AiRun, AiRunStatus, AiRunType, DocumentType, ProcessingStatus, Supplier, SupplierStatus
from app.schemas import (
    AiRunRead,
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

router = APIRouter(prefix="/suppliers", tags=["ai"], dependencies=[Depends(require_reviewer)])


def _get_supplier_with_documents(db: Session, supplier_id: uuid.UUID) -> Supplier:
    supplier = db.scalar(
        select(Supplier)
        .where(Supplier.id == supplier_id)
        .options(selectinload(Supplier.documents))
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
