import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import AuditEvent, Document, Supplier
from app.schemas import SupplierCreate, SupplierDetail, SupplierSummary
from app.services.document_policy import checklist_for
from app.services.compliance import evaluate_compliance, persist_compliance_results
from app.services.mock_erp import build_erp_preview
from app.services.portal_auth import require_reviewer

router = APIRouter(prefix="/suppliers", tags=["suppliers"], dependencies=[Depends(require_reviewer)])


@router.post("", response_model=SupplierSummary, status_code=status.HTTP_201_CREATED)
def create_supplier(payload: SupplierCreate, db: Session = Depends(get_db)) -> SupplierSummary:
    supplier = Supplier(
        name=payload.name.strip(),
        country=payload.country.strip() if payload.country else None,
        contact_email=str(payload.contact_email) if payload.contact_email else None,
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(supplier)
    db.flush()
    db.add(
        AuditEvent(
            supplier_id=supplier.id,
            action="supplier.created",
            entity_type="supplier",
            entity_id=str(supplier.id),
            details={"name": supplier.name},
        )
    )
    db.commit()
    db.refresh(supplier)
    return SupplierSummary.model_validate(supplier)


@router.get("", response_model=list[SupplierSummary])
def list_suppliers(db: Session = Depends(get_db)) -> list[SupplierSummary]:
    statement = (
        select(Supplier, func.count(Document.id).label("document_count"))
        .outerjoin(Document)
        .where(Supplier.submitted_at.is_not(None))
        .group_by(Supplier.id)
        .order_by(Supplier.created_at.desc())
    )
    return [
        SupplierSummary(
            **SupplierSummary.model_validate(supplier).model_dump(exclude={"document_count"}),
            document_count=count,
        )
        for supplier, count in db.execute(statement).all()
    ]


@router.get("/{supplier_id}", response_model=SupplierDetail)
def get_supplier(supplier_id: uuid.UUID, db: Session = Depends(get_db)) -> SupplierDetail:
    statement = (
        select(Supplier)
        .where(Supplier.id == supplier_id)
        .options(
            selectinload(Supplier.documents),
            selectinload(Supplier.audit_events),
            selectinload(Supplier.extracted_fields),
            selectinload(Supplier.ai_runs),
            selectinload(Supplier.compliance_results),
        )
    )
    supplier = db.execute(statement).scalar_one_or_none()
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier was not found.")

    checklist = checklist_for(supplier)
    if checklist.status == "synthetic_demo_policy" and (
        not supplier.compliance_results
        or any(
            result.evidence.get("kind") not in {"policy_check", "review_control"}
            for result in supplier.compliance_results
        )
    ):
        persist_compliance_results(db, supplier, evaluate_compliance(supplier))
        db.commit()
        db.refresh(supplier)
        db.expire(supplier, ["compliance_results"])

    supplier.documents.sort(key=lambda item: item.created_at, reverse=True)
    supplier.audit_events.sort(key=lambda item: item.created_at, reverse=True)
    supplier.extracted_fields.sort(
        key=lambda item: (item.field_name, item.created_at), reverse=False
    )
    supplier.ai_runs.sort(key=lambda item: item.created_at, reverse=True)
    supplier.compliance_results.sort(key=lambda item: item.rule_code)
    erp_preview = build_erp_preview(supplier)
    return SupplierDetail(
        **SupplierSummary.model_validate(supplier).model_dump(exclude={"document_count"}),
        document_count=len(supplier.documents),
        documents=supplier.documents,
        audit_events=supplier.audit_events,
        extracted_fields=supplier.extracted_fields,
        ai_runs=supplier.ai_runs[:10],
        compliance_results=supplier.compliance_results,
        tax_reference=supplier.tax_reference,
        bank_account_number=supplier.bank_account_number,
        bank_ifsc=supplier.bank_ifsc,
        requirements=checklist,
        erp_preview={
            "payload": erp_preview.payload,
            "sources": erp_preview.sources,
        },
    )
