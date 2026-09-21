"""Small, separately authenticated maintenance workspace for demo profiles."""

import secrets
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import Document, DocumentRevision, PortalAccount, PortalSession, Supplier, SupplierStatus
from app.services.portal_auth import hash_password, require_admin
from app.services.retrieval import delete_supplier_chunks, get_chunk_collection

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class AdminProfile(BaseModel):
    id: uuid.UUID
    name: str
    email: str | None
    status: SupplierStatus
    created_at: datetime
    submitted_at: datetime | None
    document_count: int
    archived_count: int


class NewPassword(BaseModel):
    password: str


@router.get("/profiles", response_model=list[AdminProfile])
def list_profiles(db: Session = Depends(get_db)) -> list[AdminProfile]:
    active = select(func.count(Document.id)).where(Document.supplier_id == Supplier.id).scalar_subquery()
    archived = select(func.count(DocumentRevision.id)).where(DocumentRevision.supplier_id == Supplier.id).scalar_subquery()
    rows = db.execute(select(Supplier, PortalAccount.email, active, archived)
                      .outerjoin(PortalAccount, Supplier.account_id == PortalAccount.id)
                      .order_by(Supplier.created_at.desc())).all()
    return [AdminProfile(id=supplier.id, name=supplier.name, email=email,
                         status=supplier.status, created_at=supplier.created_at,
                         submitted_at=supplier.submitted_at, document_count=count,
                         archived_count=history) for supplier, email, count, history in rows]


@router.post("/profiles/{supplier_id}/reset-password", response_model=NewPassword)
def reset_password(supplier_id: uuid.UUID, response: Response, db: Session = Depends(get_db)) -> NewPassword:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None or supplier.account_id is None:
        raise HTTPException(status_code=404, detail="This profile has no supplier login.")
    account = db.get(PortalAccount, supplier.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Supplier login was not found.")
    password = secrets.token_urlsafe(24)
    account.password_hash = hash_password(password)
    db.execute(delete(PortalSession).where(PortalSession.account_id == account.id))
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return NewPassword(password=password)


@router.delete("/profiles/{supplier_id}", status_code=204)
def delete_profile(supplier_id: uuid.UUID, db: Session = Depends(get_db),
                   settings: Settings = Depends(get_settings)) -> Response:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier profile was not found.")

    # Uploaded originals live only inside this supplier's UUID directory.
    upload_root = settings.upload_dir.resolve()
    directory = upload_root / str(supplier_id)
    if directory.is_symlink():
        raise HTTPException(status_code=409, detail="Supplier file storage needs inspection.")
    paths = db.scalars(select(Document.storage_path).where(Document.supplier_id == supplier_id)).all()
    paths += db.scalars(select(DocumentRevision.storage_path).where(DocumentRevision.supplier_id == supplier_id)).all()
    if any(not Path(path).resolve().is_relative_to(directory) for path in paths):
        raise HTTPException(status_code=409, detail="Supplier file storage needs inspection.")

    # Clear vector records before deleting the relational profile. A vector-store
    # failure leaves the profile available so deletion can be retried.
    delete_supplier_chunks(get_chunk_collection(), str(supplier_id))
    db.execute(delete(DocumentRevision).where(DocumentRevision.supplier_id == supplier_id))
    account = db.get(PortalAccount, supplier.account_id) if supplier.account_id else None
    if account:
        db.execute(delete(PortalSession).where(PortalSession.account_id == account.id))
    db.delete(supplier)
    db.flush()
    if account:
        db.delete(account)
    db.commit()
    if directory.exists():
        shutil.rmtree(directory)
    return Response(status_code=204)
