import uuid
import hashlib
from datetime import UTC, datetime
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
    AdditionalDocument,
    ComplianceResult,
    Document,
    DocumentRevision,
    DocumentType,
    ExtractedField,
    ProcessingStatus,
    Supplier,
    SupplierStatus,
)
from app.schemas import AdditionalDocumentRead, DocumentRead, DocumentRevisionRead
from app.services.portal_auth import require_reviewer
from app.services.document_policy import required_types_for
from app.services.documents import DocumentExtractionError, extract_document_text
from app.services.openai_service import AIConfigurationError, build_openai_service
from app.services.retrieval import delete_document_chunks, get_chunk_collection
from app.services.upload_validation import UploadValidationError, validate_staged_upload

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
    document.ocr_quality_score = extracted.ocr_quality_score
    document.ocr_quality_status = extracted.ocr_quality_status
    document.ocr_quality_details = {
        "meaning": "Estimated OCR extraction reliability; not document authenticity.",
        "visual_quality_score": extracted.ocr_quality_score,
        "page_metrics": list(extracted.ocr_quality_details),
    } if extracted.ocr_quality_score is not None else None
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
        "ocr_quality_score": document.ocr_quality_score,
        "ocr_quality_status": document.ocr_quality_status,
    }


def _archive_document_record(
    document: Document,
    supplier: Supplier,
    db: Session,
    settings: Settings,
    *,
    delete_vectors: bool = True,
) -> None:
    """Archive an active document inside the caller's transaction."""
    file_path = _private_file_path(document.storage_path, settings)
    if not file_path.is_file():
        raise HTTPException(status_code=503, detail="The current original is unavailable in file storage.")
    db.execute(delete(ExtractedField).where(ExtractedField.document_id == document.id))
    db.execute(delete(ComplianceResult).where(ComplianceResult.supplier_id == supplier.id))
    if delete_vectors:
        delete_document_chunks(get_chunk_collection(), str(supplier.id), str(document.id))
    db.add(DocumentRevision(
        id=document.id,
        supplier_id=supplier.id,
        document_type=document.document_type.value,
        revision=document.revision,
        filename=document.filename,
        storage_path=document.storage_path,
        content_type=document.content_type,
        file_size=document.file_size,
        sha256=document.sha256 or hashlib.sha256(file_path.read_bytes()).hexdigest(),
        uploaded_at=document.created_at,
    ))
    db.add(AuditEvent(
        supplier_id=supplier.id,
        action="document.archived",
        entity_type="document",
        entity_id=str(document.id),
        details={
            "filename": document.filename,
            "document_type": document.document_type.value,
            "revision": document.revision,
            "document_ai_results_cleared": True,
        },
    ))
    db.delete(document)
    db.flush()


def _record_upload_rejection(
    db: Session,
    supplier_id: uuid.UUID,
    document_type: DocumentType,
    filename: str,
    reason: str,
    issue_codes: list[str],
) -> None:
    db.add(AuditEvent(
        supplier_id=supplier_id,
        action="document.upload_rejected",
        entity_type="document",
        entity_id=None,
        details={
            "filename": filename,
            "document_type": document_type.value,
            "reason": reason[:500],
            "issue_codes": issue_codes,
            "permanent_file_created": False,
        },
    ))
    db.commit()


async def ingest_document(
    *,
    supplier: Supplier,
    document_type: DocumentType,
    file: UploadFile,
    db: Session,
    settings: Settings,
    replacement: Document | None = None,
) -> Document:
    """Validate a temporary upload completely before promoting it to permanent storage."""
    existing_document = db.scalar(select(Document).where(
        Document.supplier_id == supplier.id,
        Document.document_type == document_type,
    ))
    if existing_document is not None and (
        replacement is None or existing_document.id != replacement.id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A {document_type.value} document has already been uploaded. "
                "Delete it before uploading a replacement."
            ),
        )

    content_type = file.content_type or ""
    if content_type not in ALLOWED_CONTENT_TYPES:
        await file.close()
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type: choose a PDF, PNG, JPEG or UTF-8 plain-text file.",
        )
    contents = await file.read(settings.max_upload_size_bytes + 1)
    await file.close()
    filename = Path(file.filename or "document").name[:255]
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file: choose a file that contains readable evidence.")
    if len(contents) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Oversized file: the maximum allowed size is {settings.max_upload_size_mb} MB.",
        )

    staging_directory = settings.upload_dir.resolve() / ".staging" / str(supplier.id)
    staging_directory.mkdir(parents=True, exist_ok=True)
    staged_path = staging_directory / f"{uuid.uuid4()}{ALLOWED_CONTENT_TYPES[content_type]}"
    staged_path.write_bytes(contents)
    permanent_path: Path | None = None
    accepted = False
    replacement_id = replacement.id if replacement is not None else None
    try:
        try:
            extracted = extract_document_text(staged_path, content_type, settings)
        except DocumentExtractionError as exc:
            message = f"Unreadable file: {exc} The file was not saved."
            _record_upload_rejection(
                db, supplier.id, document_type, filename, message, ["unreadable_file"],
            )
            raise HTTPException(status_code=422, detail=message) from exc

        try:
            ai = build_openai_service(settings) if settings.upload_ai_validation_enabled else None
            validation = validate_staged_upload(
                supplier=supplier,
                expected_type=document_type,
                filename=filename,
                extracted=extracted,
                settings=settings,
                ai=ai,
            )
        except UploadValidationError as exc:
            message = "Upload rejected. " + " ".join(issue.message for issue in exc.issues)
            _record_upload_rejection(
                db,
                supplier.id,
                document_type,
                filename,
                message,
                [issue.code for issue in exc.issues],
            )
            raise HTTPException(status_code=422, detail=message) from exc
        except AIConfigurationError as exc:
            message = (
                "Upload validation could not be completed, so the file was not saved. "
                f"{str(exc)}"
            )
            _record_upload_rejection(
                db, supplier.id, document_type, filename, message, ["validation_unavailable"],
            )
            raise HTTPException(status_code=503, detail=message) from exc
        except Exception as exc:
            message = (
                "Upload validation could not be completed, so the file was not saved. "
                "The AI provider did not return a usable validation result; retry the upload."
            )
            _record_upload_rejection(
                db, supplier.id, document_type, filename, message, ["validation_unavailable"],
            )
            raise HTTPException(status_code=503, detail=message) from exc

        previous_revision = db.scalar(select(func.max(DocumentRevision.revision)).where(
            DocumentRevision.supplier_id == supplier.id,
            DocumentRevision.document_type == document_type.value,
        )) or 0
        if replacement is not None:
            previous_revision = max(previous_revision, replacement.revision)

        document_id = uuid.uuid4()
        supplier_directory = settings.upload_dir.resolve() / str(supplier.id)
        supplier_directory.mkdir(parents=True, exist_ok=True)
        permanent_path = supplier_directory / f"{document_id}{ALLOWED_CONTENT_TYPES[content_type]}"
        staged_path.replace(permanent_path)

        if replacement is not None:
            _archive_document_record(
                replacement, supplier, db, settings, delete_vectors=False,
            )

        validation_details = dict(validation.details)
        for assessment in validation_details.get("policy_assessments", []):
            assessment["document_id"] = str(document_id)
        manual_review_required = (
            validation.ocr_quality_status == "review"
            or any(field.needs_review for field in validation.fields)
        )
        review_comment = None
        if validation.ocr_quality_status == "review":
            review_comment = "OCR reliability requires manual comparison with the original document."
        elif manual_review_required:
            review_comment = "One or more extracted values require comparison with the original document."
        document = Document(
            id=document_id,
            supplier_id=supplier.id,
            document_type=document_type,
            filename=filename,
            storage_path=str(permanent_path),
            content_type=content_type,
            file_size=len(contents),
            sha256=hashlib.sha256(contents).hexdigest(),
            revision=previous_revision + 1,
            page_count=extracted.page_count,
            extracted_text=extracted.text,
            text_extraction_method=extracted.text_extraction_method,
            ocr_pages=list(extracted.ocr_pages),
            ocr_language=extracted.ocr_language,
            ocr_warnings=list(extracted.ocr_warnings),
            ocr_quality_score=validation.ocr_quality_score,
            ocr_quality_status=validation.ocr_quality_status,
            ocr_quality_details=validation.ocr_quality_details,
            redacted_text=validation.redacted_text,
            redaction_summary=validation.redaction_counts,
            processing_status=ProcessingStatus.READY,
            ai_extraction_status="ready" if validation.status == "passed" else "pending",
            ai_index_status="pending",
            upload_validation_status=validation.status,
            upload_validation_details=validation_details,
            review_status="attention" if manual_review_required else "pending",
            review_comment=review_comment,
        )
        db.add(document)
        for field in validation.fields:
            db.add(ExtractedField(
                supplier_id=supplier.id,
                document_id=document.id,
                field_name=field.field_name,
                value=field.value,
                page_number=field.page_number,
                confidence=field.confidence,
                needs_review=field.needs_review,
                review_status="attention" if field.needs_review else "pending",
            ))
        supplier.status = SupplierStatus.NEW
        supplier.decision_reason = None
        supplier.decided_at = None
        supplier.erp_supplier_id = None
        supplier.erp_record_id = None
        supplier.erp_payload = None
        db.add(AuditEvent(
            supplier_id=supplier.id,
            action="document.accepted_after_validation",
            entity_type="document",
            entity_id=str(document.id),
            details={
                "filename": filename,
                "document_type": document_type.value,
                "revision": document.revision,
                "validation_status": validation.status,
                "text_extraction_method": extracted.text_extraction_method,
                "ocr_pages": list(extracted.ocr_pages),
                "ocr_quality_score": validation.ocr_quality_score,
                "ocr_quality_status": validation.ocr_quality_status,
                "replaced_document_id": str(replacement_id) if replacement_id else None,
            },
        ))
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            permanent_path.unlink(missing_ok=True)
            permanent_path = None
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A {document_type.value} document has already been uploaded.",
            ) from exc
        accepted = True
        db.refresh(document)
        if replacement_id is not None:
            try:
                delete_document_chunks(
                    get_chunk_collection(), str(supplier.id), str(replacement_id),
                )
            except Exception:
                try:
                    db.add(AuditEvent(
                        supplier_id=supplier.id,
                        action="document.archived_vector_cleanup_failed",
                        entity_type="document",
                        entity_id=str(replacement_id),
                        details={"replacement_document_id": str(document.id)},
                    ))
                    db.commit()
                except Exception:
                    db.rollback()
        return document
    finally:
        staged_path.unlink(missing_ok=True)
        if permanent_path is not None and not accepted:
            permanent_path.unlink(missing_ok=True)


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

    return await ingest_document(
        supplier=supplier,
        document_type=document_type,
        file=file,
        db=db,
        settings=settings,
    )


@router.post(
    "/{supplier_id}/additional-documents",
    response_model=AdditionalDocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_additional_document(
    supplier_id: uuid.UUID,
    file: UploadFile = File(...),
    verification_note: str = Form(...),
    reviewer_name: str = Form("Demo reviewer"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AdditionalDocument:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None or supplier.submitted_at is None:
        raise HTTPException(status_code=404, detail="Supplier was not found.")
    if supplier.category != "OTHER":
        raise HTTPException(status_code=409, detail="Additional email evidence is available only for Other-category suppliers.")
    if supplier.status in {SupplierStatus.APPROVED, SupplierStatus.REJECTED}:
        raise HTTPException(status_code=409, detail="A finalized supplier cannot be changed.")
    note = verification_note.strip()
    reviewer = reviewer_name.strip()
    if len(note) < 10:
        raise HTTPException(status_code=422, detail="Describe what was manually verified in at least 10 characters.")
    if len(reviewer) < 2:
        raise HTTPException(status_code=422, detail="Reviewer name is required.")
    content_type = file.content_type or ""
    if content_type not in ALLOWED_CONTENT_TYPES:
        await file.close()
        raise HTTPException(status_code=415, detail="Unsupported file type: choose a PDF, PNG, JPEG or UTF-8 plain-text file.")
    contents = await file.read(settings.max_upload_size_bytes + 1)
    await file.close()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file: choose a file that contains evidence.")
    if len(contents) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail=f"Oversized file: the maximum allowed size is {settings.max_upload_size_mb} MB.")

    document_id = uuid.uuid4()
    filename = Path(file.filename or "additional-evidence").name[:255]
    directory = settings.upload_dir.resolve() / str(supplier.id) / "additional"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{document_id}{ALLOWED_CONTENT_TYPES[content_type]}"
    path.write_bytes(contents)
    record = AdditionalDocument(
        id=document_id,
        supplier_id=supplier.id,
        filename=filename,
        storage_path=str(path),
        content_type=content_type,
        file_size=len(contents),
        sha256=hashlib.sha256(contents).hexdigest(),
        uploaded_by=reviewer,
        verification_note=note,
        verified_at=datetime.now(UTC),
    )
    db.add(record)
    db.add(AuditEvent(
        supplier_id=supplier.id,
        action="supplier.additional_evidence_attached",
        entity_type="additional_document",
        entity_id=str(record.id),
        details={"filename": filename, "reviewer_name": reviewer, "manually_verified": True},
    ))
    try:
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    db.refresh(record)
    return record


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
    assert supplier is not None
    _archive_document_record(document, supplier, db, settings)
    supplier.status = SupplierStatus.NEW
    supplier.decision_reason = None
    supplier.decided_at = None
    supplier.erp_supplier_id = None
    supplier.erp_record_id = None
    supplier.erp_payload = None
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


@router.get("/{supplier_id}/additional-documents/{document_id}/content")
def reviewer_additional_document_content(
    supplier_id: uuid.UUID,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    record = db.scalar(select(AdditionalDocument).where(
        AdditionalDocument.id == document_id,
        AdditionalDocument.supplier_id == supplier_id,
    ))
    if record is None:
        raise HTTPException(status_code=404, detail="Additional evidence was not found.")
    path = _private_file_path(record.storage_path, settings)
    if not path.is_file():
        raise HTTPException(status_code=503, detail="The additional evidence is unavailable in file storage.")
    if hashlib.sha256(path.read_bytes()).hexdigest() != record.sha256:
        raise HTTPException(status_code=409, detail="The stored additional evidence failed its integrity check.")
    db.add(AuditEvent(
        supplier_id=supplier_id,
        action="supplier.additional_evidence_viewed",
        entity_type="additional_document",
        entity_id=str(document_id),
        details={"actor": "reviewer"},
    ))
    db.commit()
    return FileResponse(
        path,
        media_type=record.content_type,
        filename=record.filename,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
