import uuid
import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import (
    AuditEvent,
    ComplianceResult,
    Document,
    DocumentRevision,
    DocumentType,
    ExtractedField,
    ProcessingStatus,
    Supplier,
    SupplierStatus,
)
from app.schemas import DocumentRead, DocumentRevisionRead
from app.services.portal_auth import require_reviewer
from app.services.document_policy import required_types_for
from app.services.documents import DocumentExtractionError, extract_document_text
from app.services.retrieval import delete_document_chunks, get_chunk_collection

router = APIRouter(prefix="/suppliers", tags=["documents"], dependencies=[Depends(require_reviewer)])
ALLOWED_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


def _apply_text_extraction(document: Document, file_path: Path, settings: Settings) -> dict:
    extracted = extract_document_text(file_path, document.content_type, settings)
    document.extracted_text = extracted.text
    document.page_count = extracted.page_count
    document.text_extraction_method = extracted.text_extraction_method
    document.ocr_pages = list(extracted.ocr_pages)
    document.ocr_language = extracted.ocr_language
    document.ocr_warnings = list(extracted.ocr_warnings)
    document.processing_status = ProcessingStatus.READY
    document.error_message = None
    document.ai_extraction_status = "pending"
    document.ai_extraction_error = None
    document.ai_index_status = "pending"
    document.ai_index_error = None
    return {
        "filename": document.filename,
        "pages": document.page_count,
        "text_extraction_method": document.text_extraction_method,
        "ocr_pages": document.ocr_pages,
        "ocr_language": document.ocr_language,
        "ocr_warnings": document.ocr_warnings,
    }


@router.post(
    "/{supplier_id}/documents",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    supplier_id: uuid.UUID,
    document_type: DocumentType = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Document:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier was not found.")
    if supplier.status in {SupplierStatus.APPROVED, SupplierStatus.REJECTED}:
        raise HTTPException(
            status_code=409,
            detail="A finalized supplier cannot be changed in this demo workflow.",
        )
    if document_type not in required_types_for(supplier):
        raise HTTPException(status_code=422, detail="This document type is not in the selected checklist.")

    existing_document = db.scalar(
        select(Document).where(
            Document.supplier_id == supplier_id,
            Document.document_type == document_type,
        )
    )
    if existing_document is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A {document_type.value} document has already been uploaded. "
                "Delete it before uploading a replacement."
            ),
        )

    content_type = file.content_type or ""
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Only PDF, PNG, JPEG and plain-text files are supported.")

    contents = await file.read(settings.max_upload_size_bytes + 1)
    await file.close()
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(contents) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Files must not exceed {settings.max_upload_size_mb} MB.",
        )

    supplier_directory = settings.upload_dir.resolve() / str(supplier_id)
    supplier_directory.mkdir(parents=True, exist_ok=True)
    document_id = uuid.uuid4()
    file_path = supplier_directory / f"{document_id}{ALLOWED_CONTENT_TYPES[content_type]}"
    file_path.write_bytes(contents)

    previous_revision = db.scalar(select(func.max(DocumentRevision.revision)).where(
        DocumentRevision.supplier_id == supplier_id,
        DocumentRevision.document_type == document_type.value,
    )) or 0

    document = Document(
        id=document_id,
        supplier_id=supplier_id,
        document_type=document_type,
        filename=Path(file.filename or "document").name[:255],
        storage_path=str(file_path),
        content_type=content_type,
        file_size=len(contents),
        sha256=hashlib.sha256(contents).hexdigest(),
        revision=previous_revision + 1,
        processing_status=ProcessingStatus.PROCESSING,
    )
    db.add(document)

    try:
        audit_details = _apply_text_extraction(document, file_path, settings)
        audit_action = "document.ready"
    except DocumentExtractionError as exc:
        document.processing_status = ProcessingStatus.FAILED
        document.error_message = str(exc)
        audit_action = "document.failed"
        audit_details = {"filename": document.filename, "reason": str(exc)}

    db.add(
        AuditEvent(
            supplier_id=supplier_id,
            action=audit_action,
            entity_type="document",
            entity_id=str(document.id),
            details=audit_details,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A {document_type.value} document has already been uploaded. "
                "Delete it before uploading a replacement."
            ),
        ) from exc
    db.refresh(document)
    return document


def retry_text_extraction(
    document: Document, db: Session, settings: Settings, *, actor: str,
) -> Document:
    if document.processing_status != ProcessingStatus.FAILED:
        raise HTTPException(status_code=409, detail="Text extraction can only be retried for a failed document.")
    file_path = _private_file_path(document.storage_path, settings)
    if not file_path.is_file():
        raise HTTPException(status_code=503, detail="The original document is unavailable in file storage.")
    if document.sha256 and hashlib.sha256(file_path.read_bytes()).hexdigest() != document.sha256:
        raise HTTPException(status_code=409, detail="The stored original failed its integrity check.")

    document.processing_status = ProcessingStatus.PROCESSING
    document.error_message = None
    db.commit()
    try:
        details = _apply_text_extraction(document, file_path, settings)
        details.update({"actor": actor, "retry": True})
        db.add(AuditEvent(
            supplier_id=document.supplier_id,
            action="document.text_extraction_retried",
            entity_type="document",
            entity_id=str(document.id),
            details=details,
        ))
        db.commit()
    except DocumentExtractionError as exc:
        document.processing_status = ProcessingStatus.FAILED
        document.error_message = str(exc)
        db.add(AuditEvent(
            supplier_id=document.supplier_id,
            action="document.text_extraction_retry_failed",
            entity_type="document",
            entity_id=str(document.id),
            details={"actor": actor, "filename": document.filename, "reason": str(exc)},
        ))
        db.commit()
    db.refresh(document)
    return document


@router.post(
    "/{supplier_id}/documents/{document_id}/text-extraction/retry",
    response_model=DocumentRead,
)
def retry_reviewer_document_text_extraction(
    supplier_id: uuid.UUID,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Document:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None or (supplier.account_id is not None and supplier.submitted_at is None):
        raise HTTPException(status_code=404, detail="Supplier was not found.")
    if supplier.status in {SupplierStatus.APPROVED, SupplierStatus.REJECTED}:
        raise HTTPException(status_code=409, detail="A finalized supplier cannot be reprocessed.")
    document = db.scalar(select(Document).where(
        Document.id == document_id,
        Document.supplier_id == supplier_id,
    ))
    if document is None:
        raise HTTPException(status_code=404, detail="Document was not found.")
    return retry_text_extraction(document, db, settings, actor="reviewer")


@router.delete(
    "/{supplier_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_document(
    supplier_id: uuid.UUID,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.supplier_id == supplier_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document was not found.")

    file_path = _private_file_path(document.storage_path, settings)
    if not file_path.is_file():
        raise HTTPException(status_code=503, detail="The original document is unavailable in file storage.")
    supplier = db.get(Supplier, supplier_id)
    if supplier is not None and supplier.status in {
        SupplierStatus.APPROVED,
        SupplierStatus.REJECTED,
    }:
        raise HTTPException(
            status_code=409,
            detail="A finalized supplier cannot be changed in this demo workflow.",
        )
    db.execute(
        delete(ExtractedField).where(ExtractedField.document_id == document_id)
    )
    db.execute(
        delete(ComplianceResult).where(ComplianceResult.supplier_id == supplier_id)
    )
    delete_document_chunks(
        get_chunk_collection(), str(supplier_id), str(document_id)
    )
    if supplier is not None:
        supplier.status = SupplierStatus.NEW
        supplier.decision_reason = None
        supplier.decided_at = None
        supplier.erp_supplier_id = None
        supplier.erp_payload = None
    db.add(DocumentRevision(
        id=document.id, supplier_id=supplier_id,
        document_type=document.document_type.value, revision=document.revision,
        filename=document.filename, storage_path=document.storage_path,
        content_type=document.content_type, file_size=document.file_size,
        sha256=document.sha256 or hashlib.sha256(file_path.read_bytes()).hexdigest(),
        uploaded_at=document.created_at,
    ))
    db.add(
        AuditEvent(
            supplier_id=supplier_id,
            action="document.archived",
            entity_type="document",
            entity_id=str(document.id),
            details={
                "filename": document.filename,
                "document_type": document.document_type.value,
                "revision": document.revision,
                "document_ai_results_cleared": True,
            },
        )
    )
    db.delete(document)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _private_file_path(storage_path: str, settings: Settings) -> Path:
    path = Path(storage_path).resolve()
    if not path.is_relative_to(settings.upload_dir.resolve()):
        raise HTTPException(status_code=404, detail="Document was not found.")
    return path


def original_file_response(
    db: Session, supplier_id: uuid.UUID, document_id: uuid.UUID, settings: Settings,
    *, actor: str,
) -> FileResponse:
    active = db.scalar(select(Document).where(Document.id == document_id, Document.supplier_id == supplier_id))
    archived = None if active else db.scalar(select(DocumentRevision).where(
        DocumentRevision.id == document_id, DocumentRevision.supplier_id == supplier_id,
    ))
    record = active or archived
    if record is None:
        raise HTTPException(status_code=404, detail="Document was not found.")
    path = _private_file_path(record.storage_path, settings)
    if not path.is_file():
        raise HTTPException(status_code=503, detail="The original document is unavailable in file storage.")
    if record.sha256 and hashlib.sha256(path.read_bytes()).hexdigest() != record.sha256:
        raise HTTPException(status_code=409, detail="The stored original failed its integrity check.")
    db.add(AuditEvent(
        supplier_id=supplier_id, action="document.viewed", entity_type="document",
        entity_id=str(document_id), details={"actor": actor, "archived": active is None},
    ))
    db.commit()
    return FileResponse(
        path, media_type=record.content_type, filename=record.filename,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


def document_history(db: Session, supplier_id: uuid.UUID) -> list[DocumentRevisionRead]:
    versions = db.scalars(select(DocumentRevision).where(
        DocumentRevision.supplier_id == supplier_id,
    ).order_by(DocumentRevision.archived_at.desc())).all()
    return [DocumentRevisionRead.model_validate(item) for item in versions]


@router.get("/{supplier_id}/documents/history", response_model=list[DocumentRevisionRead])
def reviewer_document_history(supplier_id: uuid.UUID, db: Session = Depends(get_db)) -> list[DocumentRevisionRead]:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None or (supplier.account_id is not None and supplier.submitted_at is None):
        raise HTTPException(status_code=404, detail="Supplier was not found.")
    return document_history(db, supplier_id)


@router.get("/{supplier_id}/documents/{document_id}/content")
def reviewer_document_content(
    supplier_id: uuid.UUID, document_id: uuid.UUID,
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> FileResponse:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None or (supplier.account_id is not None and supplier.submitted_at is None):
        raise HTTPException(status_code=404, detail="Supplier was not found.")
    return original_file_response(db, supplier_id, document_id, settings, actor="reviewer")
