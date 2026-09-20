"""Separate supplier self-service from the internal reviewer demo."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import Document, DocumentType, PortalAccount, PortalSession, ProcessingStatus, Supplier, SupplierStatus
from app.routers.documents import delete_document, upload_document
from app.schemas import DocumentRead
from app.services.document_policy import Checklist, Policy, checklist_for, load_policy, required_types_for, subcategory_for
from app.services.portal_auth import (
    create_session, current_session, hash_password, require_supplier, verify_password,
)

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


@router.patch("/application", response_model=ApplicationRead)
def save_application(payload: ApplicationUpdate, session: PortalSession = Depends(require_supplier), db: Session = Depends(get_db)) -> ApplicationRead:
    supplier = get_application(db, session)
    if supplier.submitted_at or supplier.status in {SupplierStatus.APPROVED, SupplierStatus.REJECTED}:
        raise HTTPException(status_code=409, detail="This application has already been submitted.")
    if not subcategory_for(payload.category, payload.subcategory):
        raise HTTPException(status_code=422, detail="Choose a primary category and subcategory from the policy list.")
    if payload.country is not None and payload.country.strip() != "India":
        raise HTTPException(status_code=422, detail="The synthetic v1.1 policy only covers India-based suppliers.")
    supplier.category = payload.category.strip()
    supplier.subcategory = payload.subcategory.strip()
    if payload.name is not None:
        supplier.name = payload.name.strip()
    if payload.country is not None:
        supplier.country = payload.country.strip()
    if payload.contact_email is not None:
        supplier.contact_email = str(payload.contact_email)
    for field in ("tax_reference", "bank_account_number", "bank_ifsc"):
        value = getattr(payload, field)
        if value is not None:
            setattr(supplier, field, value.strip())
    db.commit()
    db.refresh(supplier)
    return application_response(db, supplier)


@router.post("/application/submit", response_model=ApplicationRead)
def submit_application(session: PortalSession = Depends(require_supplier), db: Session = Depends(get_db)) -> ApplicationRead:
    supplier = get_application(db, session)
    if not subcategory_for(supplier.category or "", supplier.subcategory or "") or supplier.name == "New application" or supplier.country != "India":
        raise HTTPException(status_code=422, detail="Choose a policy category and complete your India-based business details first.")
    if not all((supplier.contact_email, supplier.tax_reference, supplier.bank_account_number, supplier.bank_ifsc)):
        raise HTTPException(status_code=422, detail="Contact email, tax reference, bank account number and IFSC are required portal fields.")
    required = required_types_for(supplier)
    uploaded = set(db.scalars(select(Document.document_type).where(
        Document.supplier_id == supplier.id,
    )).all())
    ready = set(db.scalars(select(Document.document_type).where(
        Document.supplier_id == supplier.id,
        Document.processing_status == ProcessingStatus.READY,
    )).all())
    if ready != required or uploaded != required:
        missing = sorted(item.value for item in required - ready)
        extra = sorted(item.value for item in uploaded - required)
        raise HTTPException(status_code=422, detail=(
            f"Remove documents no longer required: {', '.join(extra)}." if extra
            else f"Upload ready documents for: {', '.join(missing)}."
        ))
    if supplier.submitted_at is None:
        supplier.requirements_snapshot = checklist_for(supplier).model_dump(mode="json")
        supplier.submitted_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(supplier)
    return application_response(db, supplier)


@router.post("/application/documents", response_model=DocumentRead, status_code=201)
async def upload_application_document(
    document_type: DocumentType = Form(...), file: UploadFile = File(...),
    session: PortalSession = Depends(require_supplier), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    supplier = get_application(db, session)
    if supplier.submitted_at or not supplier.category or not supplier.country:
        raise HTTPException(status_code=409, detail="Complete your details before uploading, or this application is already submitted.")
    if document_type not in required_types_for(supplier):
        raise HTTPException(status_code=422, detail="This document type is not in your current checklist.")
    return await upload_document(supplier.id, document_type, file, db, settings)


@router.delete("/application/documents/{document_id}", status_code=204)
def delete_application_document(
    document_id: uuid.UUID, session: PortalSession = Depends(require_supplier),
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> Response:
    supplier = get_application(db, session)
    if supplier.submitted_at:
        raise HTTPException(status_code=409, detail="This application has already been submitted.")
    return delete_document(supplier.id, document_id, db, settings)
