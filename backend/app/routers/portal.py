"""Separate supplier self-service from the internal reviewer demo."""

import uuid
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import SessionLocal, get_db
from app.models import AuditEvent, Document, DocumentType, PortalAccount, PortalSession, ProcessingStatus, Supplier, SupplierStatus
from app.routers.documents import delete_document, document_history, original_file_response, upload_document
from app.schemas import (
    AssistantHistoryMessage, DocumentRead, DocumentRevisionRead, GeneralAssistantMessage, GeneralAssistantRequest,
    GeneralAssistantResponse, GeneralAssistantRun,
)
from app.routers.assistant import answer_chat
from app.services.document_policy import Checklist, Policy, checklist_for, load_policy, required_types_for, subcategory_for
from app.services.portal_auth import (
    create_session, current_session, hash_password, require_supplier, verify_password,
)
from app.services.openai_service import build_openai_service
from app.services.processing import process_supplier_documents
from app.services.policy_retrieval import application_answer_for, application_context_for
from app.services.retrieval import get_chunk_collection
from app.services.compliance import evaluate_compliance, persist_compliance_results
from app.services.assistant_history import clear_history, conversation_history, save_exchange

router = APIRouter(prefix="/portal", tags=["portal"])


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class SessionResponse(BaseModel):
    token: str
    role: str
    email: str | None = None


class ApplicationUpdate(BaseModel):
    category: str = Field(min_length=2, max_length=100)
    subcategory: str = Field(min_length=2, max_length=100)
    name: str | None = Field(default=None, min_length=2, max_length=200)
    country: str | None = Field(default=None, min_length=2, max_length=100)
    contact_email: EmailStr | None = None
    tax_reference: str | None = Field(default=None, max_length=100)
    bank_account_number: str | None = Field(default=None, max_length=100)
    bank_ifsc: str | None = Field(default=None, max_length=20)


class ApplicationRead(BaseModel):
    id: uuid.UUID
    category: str | None
    subcategory: str | None
    name: str
    country: str | None
    contact_email: str | None
    tax_reference: str | None
    bank_account_number: str | None
    bank_ifsc: str | None
    submitted_at: datetime | None
    status: SupplierStatus
    documents: list[DocumentRead]
    requirements: Checklist


def get_application(db: Session, session: PortalSession) -> Supplier:
    supplier = db.scalar(select(Supplier).where(Supplier.account_id == session.account_id))
    if supplier is None:
        raise HTTPException(status_code=404, detail="Application was not found.")
    return supplier


def application_response(db: Session, supplier: Supplier) -> ApplicationRead:
    documents = db.scalars(select(Document).where(Document.supplier_id == supplier.id).order_by(Document.created_at.desc())).all()
    return ApplicationRead(
        id=supplier.id, category=supplier.category, subcategory=supplier.subcategory,
        name=supplier.name, country=supplier.country, contact_email=supplier.contact_email,
        tax_reference=supplier.tax_reference, bank_account_number=supplier.bank_account_number,
        bank_ifsc=supplier.bank_ifsc,
        submitted_at=supplier.submitted_at, status=supplier.status,
        documents=[DocumentRead.model_validate(item) for item in documents],
        requirements=checklist_for(supplier),
    )


def correction_open(supplier: Supplier) -> bool:
    return bool(
        supplier.submitted_at
        and (
            supplier.status == SupplierStatus.NEW
            or any(document.review_status == "disputed" for document in supplier.documents)
        )
    )


def process_submitted_application(supplier_id: uuid.UUID, settings: Settings) -> None:
    """Run document AI after the submission response has been sent."""
    with SessionLocal() as db:
        supplier = db.get(Supplier, supplier_id)
        if supplier is None or supplier.submitted_at is None:
            return
        try:
            process_supplier_documents(
                db=db,
                supplier=supplier,
                settings=settings,
                ai=build_openai_service(settings),
                collection=get_chunk_collection(),
            )
        except Exception:
            # Processing records its safe failure state for the reviewer. Submission
            # remains valid and must never be rolled back by an AI/provider failure.
            pass


@router.post("/auth/register", response_model=SessionResponse, status_code=201)
def register(payload: Credentials, db: Session = Depends(get_db)) -> SessionResponse:
    email = str(payload.email).lower()
    if db.scalar(select(PortalAccount.id).where(PortalAccount.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists. Sign in instead.")
    account = PortalAccount(email=email, password_hash=hash_password(payload.password))
    db.add(account)
    db.flush()
    db.add(Supplier(name="New application", contact_email=email, account_id=account.id))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists. Sign in instead.") from exc
    return SessionResponse(token=create_session(db, "supplier", account.id), role="supplier", email=email)


@router.post("/auth/login", response_model=SessionResponse)
def login(payload: Credentials, db: Session = Depends(get_db)) -> SessionResponse:
    email = str(payload.email).lower()
    account = db.scalar(select(PortalAccount).where(PortalAccount.email == email))
    if account is None or not verify_password(payload.password, account.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return SessionResponse(token=create_session(db, "supplier", account.id), role="supplier", email=email)


@router.post("/auth/reviewer-demo", response_model=SessionResponse)
def reviewer_demo(db: Session = Depends(get_db)) -> SessionResponse:
    # Intentionally open for the capstone demo. Replace with company SSO before real use.
    return SessionResponse(token=create_session(db, "reviewer"), role="reviewer")


@router.post("/auth/admin", response_model=SessionResponse)
def admin_login(payload: Credentials, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> SessionResponse:
    configured_password = settings.admin_password.get_secret_value() if settings.admin_password else ""
    if (not settings.admin_email or not configured_password
        or not secrets.compare_digest(str(payload.email).lower(), settings.admin_email.strip().lower())
        or not secrets.compare_digest(payload.password, configured_password)):
        raise HTTPException(status_code=401, detail="Admin credentials are incorrect or not configured.")
    return SessionResponse(token=create_session(db, "admin"), role="admin", email=settings.admin_email)


@router.get("/auth/session", response_model=SessionResponse)
def session_info(session: PortalSession = Depends(current_session), db: Session = Depends(get_db)) -> SessionResponse:
    account = db.get(PortalAccount, session.account_id) if session.account_id else None
    return SessionResponse(token="", role=session.role, email=account.email if account else None)


@router.post("/auth/logout", status_code=204)
def logout(session: PortalSession = Depends(current_session), db: Session = Depends(get_db)) -> Response:
    db.delete(session)
    db.commit()
    return Response(status_code=204)


@router.get("/application", response_model=ApplicationRead)
def read_application(session: PortalSession = Depends(require_supplier), db: Session = Depends(get_db)) -> ApplicationRead:
    return application_response(db, get_application(db, session))


@router.get("/policy", response_model=Policy)
def policy_catalog() -> Policy:
    """Public taxonomy and evidence guidance; no supplier data or AI provider needed."""
    return load_policy()


@router.get("/application/assistant/history", response_model=list[AssistantHistoryMessage])
def application_assistant_history(
    session: PortalSession = Depends(require_supplier), db: Session = Depends(get_db),
) -> list[AssistantHistoryMessage]:
    supplier = get_application(db, session)
    return [AssistantHistoryMessage.model_validate(item) for item in conversation_history(db, supplier.id, "supplier", limit=50)]


@router.delete("/application/assistant/history", status_code=204)
def clear_application_assistant_history(
    session: PortalSession = Depends(require_supplier), db: Session = Depends(get_db),
) -> Response:
    supplier = get_application(db, session)
    clear_history(db, supplier.id, "supplier")
    return Response(status_code=204)


@router.post("/application/assistant", response_model=GeneralAssistantResponse)
def application_assistant(
    payload: GeneralAssistantRequest,
    session: PortalSession = Depends(require_supplier),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GeneralAssistantResponse:
    if payload.messages[-1].role != "user":
        raise HTTPException(status_code=422, detail="The last message must be a user question.")
    if sum(len(message.content) for message in payload.messages) > 10000:
        raise HTTPException(status_code=422, detail="The conversation is too long. Start a new chat.")
    supplier = get_application(db, session)
    question = payload.messages[-1].content.strip()
    if len(question) < 3:
        raise HTTPException(status_code=422, detail="Enter a question with at least three characters.")
    prior = conversation_history(db, supplier.id, "supplier")
    messages = [
        GeneralAssistantMessage(role=item.role, content=item.content)
        for item in prior
    ] + [GeneralAssistantMessage(role="user", content=question)]
    while len(messages) > 12 or (len(messages) > 1 and sum(len(item.content) for item in messages) > 10000):
        messages.pop(0)
    persisted_payload = GeneralAssistantRequest(messages=messages)

    direct_answer = application_answer_for(supplier, question)
    if direct_answer:
        response = GeneralAssistantResponse(
            answer=direct_answer,
            run=GeneralAssistantRun(
                model="application-state", prompt_version="deterministic-v1",
                input_tokens=0, output_tokens=0, latency_ms=0, redaction_counts={},
            ),
        )
    else:
        response = answer_chat(persisted_payload, settings, application_context_for(supplier))
    save_exchange(db, supplier.id, "supplier", question, response.answer)
    return response


@router.patch("/application", response_model=ApplicationRead)
def save_application(payload: ApplicationUpdate, session: PortalSession = Depends(require_supplier), db: Session = Depends(get_db)) -> ApplicationRead:
    supplier = get_application(db, session)
    if supplier.status in {SupplierStatus.APPROVED, SupplierStatus.REJECTED}:
        raise HTTPException(status_code=409, detail="This application has already been submitted.")
    correcting = correction_open(supplier)
    if supplier.submitted_at and not correcting:
        raise HTTPException(status_code=409, detail="Submitted details can only be changed after a reviewer requests corrections.")
    if not subcategory_for(payload.category, payload.subcategory):
        raise HTTPException(status_code=422, detail="Choose a primary category and subcategory from the policy list.")
    if correcting and (
        payload.category.strip() != supplier.category
        or payload.subcategory.strip() != supplier.subcategory
    ):
        raise HTTPException(status_code=409, detail="Category and subcategory cannot be changed during a correction cycle.")
    if payload.country is not None and payload.country.strip() != "India":
        raise HTTPException(status_code=422, detail="This application is available to India-based suppliers.")
    supplier.category = payload.category.strip()
    supplier.subcategory = payload.subcategory.strip()
    if payload.name is not None:
        supplier.name = payload.name.strip()
        supplier.country = "India"  # Only one country is in scope; correct older drafts on details save.
    elif payload.country is not None:
        supplier.country = "India"
    if payload.contact_email is not None:
        supplier.contact_email = str(payload.contact_email)
    for field in ("tax_reference", "bank_account_number", "bank_ifsc"):
        value = getattr(payload, field)
        if value is not None:
            setattr(supplier, field, value.strip())
    if correcting:
        supplier.status = SupplierStatus.NEW
        supplier.decision_reason = "Supplier is preparing reviewer-requested corrections."
        db.add(AuditEvent(
            supplier_id=supplier.id,
            action="application.corrections_saved",
            entity_type="supplier",
            entity_id=str(supplier.id),
            details={"supplier_updated_fields": [
                "name", "contact_email", "tax_reference", "bank_account_number", "bank_ifsc",
            ]},
        ))
    db.commit()
    db.refresh(supplier)
    return application_response(db, supplier)


@router.post("/application/resubmit", response_model=ApplicationRead)
def resubmit_application(
    background_tasks: BackgroundTasks,
    session: PortalSession = Depends(require_supplier), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ApplicationRead:
    supplier = get_application(db, session)
    if supplier.status in {SupplierStatus.APPROVED, SupplierStatus.REJECTED}:
        raise HTTPException(status_code=409, detail="A finalized application cannot be resubmitted.")
    if not correction_open(supplier):
        raise HTTPException(status_code=409, detail="There are no reviewer-requested corrections to resubmit.")
    required = required_types_for(supplier)
    documents = list(db.scalars(select(Document).where(Document.supplier_id == supplier.id)).all())
    uploaded = {document.document_type for document in documents}
    ready = {
        document.document_type for document in documents
        if document.processing_status == ProcessingStatus.READY
    }
    if uploaded != required or ready != required:
        raise HTTPException(status_code=422, detail="Upload a ready document for every required item before resubmitting.")
    for document in documents:
        if document.review_status == "disputed":
            document.review_status = "pending"
            document.review_comment = None
            document.reviewed_by = None
            document.reviewed_at = None
    supplier.status = SupplierStatus.NEEDS_REVIEW
    supplier.submitted_at = datetime.now(timezone.utc)
    supplier.decision_reason = None
    db.add(AuditEvent(
        supplier_id=supplier.id,
        action="application.corrections_resubmitted",
        entity_type="supplier",
        entity_id=str(supplier.id),
        details={"document_count": len(documents)},
    ))
    persist_compliance_results(db, supplier, evaluate_compliance(supplier))
    db.commit()
    db.refresh(supplier)
    if settings.ai_configured:
        background_tasks.add_task(process_submitted_application, supplier.id, settings)
    return application_response(db, supplier)


@router.post("/application/submit", response_model=ApplicationRead)
def submit_application(
    background_tasks: BackgroundTasks,
    session: PortalSession = Depends(require_supplier), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ApplicationRead:
    supplier = get_application(db, session)
    if not subcategory_for(supplier.category or "", supplier.subcategory or "") or supplier.name == "New application" or supplier.country != "India":
        raise HTTPException(status_code=422, detail="Choose a service category and complete your business details first.")
    if not all((supplier.contact_email, supplier.tax_reference, supplier.bank_account_number, supplier.bank_ifsc)):
        raise HTTPException(status_code=422, detail="Contact email, tax reference, bank account number and IFSC are required portal fields.")
    checklist = checklist_for(supplier)
    required = required_types_for(supplier)
    uploaded = set(db.scalars(select(Document.document_type).where(
        Document.supplier_id == supplier.id,
    )).all())
    ready = set(db.scalars(select(Document.document_type).where(
        Document.supplier_id == supplier.id,
        Document.processing_status == ProcessingStatus.READY,
    )).all())
    if ready != required or uploaded != required:
        labels = {item.document_type: item.label for item in checklist.documents}
        missing = sorted(labels[item] for item in required - ready)
        extra = uploaded - required
        raise HTTPException(status_code=422, detail=(
            "Remove documents no longer required before submitting." if extra
            else f"Upload ready documents for: {', '.join(missing)}."
        ))
    if supplier.submitted_at is None:
        supplier.requirements_snapshot = checklist_for(supplier).model_dump(mode="json")
        supplier.submitted_at = datetime.now(timezone.utc)
        supplier.status = SupplierStatus.NEEDS_REVIEW
        db.commit()
        db.refresh(supplier)
        if settings.ai_configured:
            background_tasks.add_task(process_submitted_application, supplier.id, settings)
    return application_response(db, supplier)


@router.post("/application/documents", response_model=DocumentRead, status_code=201)
async def upload_application_document(
    document_type: DocumentType = Form(...), file: UploadFile = File(...),
    session: PortalSession = Depends(require_supplier), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    supplier = get_application(db, session)
    correcting = correction_open(supplier)
    if (supplier.submitted_at and not correcting) or not supplier.category or supplier.country != "India":
        raise HTTPException(status_code=409, detail="Complete your details before uploading, or this application is already submitted.")
    if document_type not in required_types_for(supplier):
        raise HTTPException(status_code=422, detail="This document type is not in your current checklist.")
    if supplier.submitted_at:
        existing = db.scalar(select(Document).where(
            Document.supplier_id == supplier.id,
            Document.document_type == document_type,
        ))
        if existing is not None and existing.review_status != "disputed":
            raise HTTPException(status_code=409, detail="Only evidence flagged by the reviewer can be replaced.")
        if existing is not None:
            delete_document(supplier.id, existing.id, db, settings)
    document = await upload_document(supplier.id, document_type, file, db, settings)
    if supplier.submitted_at:
        supplier = get_application(db, session)
        supplier.status = SupplierStatus.NEW
        supplier.decision_reason = "Supplier is preparing reviewer-requested corrections."
        db.add(AuditEvent(
            supplier_id=supplier.id,
            action="application.flagged_document_replaced",
            entity_type="document",
            entity_id=str(document.id),
            details={"document_type": document_type.value, "revision": document.revision},
        ))
        db.commit()
        db.refresh(document)
    return document


@router.delete("/application/documents/{document_id}", status_code=204)
def delete_application_document(
    document_id: uuid.UUID, session: PortalSession = Depends(require_supplier),
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> Response:
    supplier = get_application(db, session)
    if supplier.submitted_at:
        raise HTTPException(status_code=409, detail="This application has already been submitted.")
    return delete_document(supplier.id, document_id, db, settings)


@router.get("/application/documents/history", response_model=list[DocumentRevisionRead])
def application_document_history(
    session: PortalSession = Depends(require_supplier), db: Session = Depends(get_db),
) -> list[DocumentRevisionRead]:
    return document_history(db, get_application(db, session).id)


@router.get("/application/documents/{document_id}/content")
def application_document_content(
    document_id: uuid.UUID, session: PortalSession = Depends(require_supplier),
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> FileResponse:
    supplier = get_application(db, session)
    return original_file_response(db, supplier.id, document_id, settings, actor="supplier")
