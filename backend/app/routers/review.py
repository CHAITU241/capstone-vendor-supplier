import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.metrics import record_compliance_checks, record_supplier_decision
from app.models import (
    AuditEvent,
    ComplianceResult,
    ExtractedField,
    Supplier,
    SupplierStatus,
)
from app.schemas import (
    ApprovalRequest,
    ComplianceResultRead,
    ComplianceRunResponse,
    DecisionResponse,
    ExtractedFieldRead,
    ExtractedFieldUpdate,
    RejectionRequest,
)
from app.services.compliance import (
    approval_ready,
    evaluate_compliance,
    persist_compliance_results,
)
from app.services.mock_erp import get_mock_erp_service

router = APIRouter(prefix="/suppliers", tags=["review"])


def _get_review_supplier(db: Session, supplier_id: uuid.UUID) -> Supplier:
    supplier = db.scalar(
        select(Supplier)
        .where(Supplier.id == supplier_id)
        .options(
            selectinload(Supplier.documents),
            selectinload(Supplier.extracted_fields),
            selectinload(Supplier.compliance_results),
        )
    )
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier was not found.")
    return supplier


def _ensure_reviewable(supplier: Supplier) -> None:
    if supplier.status in {SupplierStatus.APPROVED, SupplierStatus.REJECTED}:
        raise HTTPException(
            status_code=409,
            detail="A finalized supplier cannot be changed in this demo workflow.",
        )


def _compliance_response(results: list[ComplianceResult]) -> ComplianceRunResponse:
    ordered = sorted(results, key=lambda item: item.rule_code)
    return ComplianceRunResponse(
        results=[ComplianceResultRead.model_validate(item) for item in ordered],
        approval_ready=approval_ready(results),
    )


@router.get("/{supplier_id}/compliance", response_model=ComplianceRunResponse)
def get_compliance(
    supplier_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ComplianceRunResponse:
    supplier = _get_review_supplier(db, supplier_id)
    return _compliance_response(supplier.compliance_results)


@router.post("/{supplier_id}/compliance/run", response_model=ComplianceRunResponse)
def run_compliance(
    supplier_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ComplianceRunResponse:
    supplier = _get_review_supplier(db, supplier_id)
    _ensure_reviewable(supplier)
    results = persist_compliance_results(db, supplier, evaluate_compliance(supplier))
    db.commit()
    for result in results:
        db.refresh(result)
    record_compliance_checks([result.status.value for result in results])
    return _compliance_response(results)


@router.patch(
    "/{supplier_id}/fields/{field_id}",
    response_model=ExtractedFieldRead,
)
def correct_extracted_field(
    supplier_id: uuid.UUID,
    field_id: uuid.UUID,
    payload: ExtractedFieldUpdate,
    db: Session = Depends(get_db),
) -> ExtractedFieldRead:
    supplier = _get_review_supplier(db, supplier_id)
    _ensure_reviewable(supplier)
    field = db.scalar(
        select(ExtractedField).where(
            ExtractedField.id == field_id,
            ExtractedField.supplier_id == supplier_id,
        )
    )
    if field is None:
        raise HTTPException(status_code=404, detail="Extracted field was not found.")
    source_document = next(
        (document for document in supplier.documents if document.id == field.document_id),
        None,
    )
    if source_document is None or payload.page_number > max(source_document.page_count, 1):
        raise HTTPException(
            status_code=422,
            detail="Page number is outside the source document.",
        )

    field.value = payload.value.strip()
    field.page_number = payload.page_number
    field.confidence = 1.0
    field.needs_review = False
    supplier.status = SupplierStatus.NEEDS_REVIEW
    db.execute(
        delete(ComplianceResult).where(ComplianceResult.supplier_id == supplier_id)
    )
    db.add(
        AuditEvent(
            supplier_id=supplier_id,
            action="extracted_field.corrected",
            entity_type="extracted_field",
            entity_id=str(field.id),
            details={
                "field_name": field.field_name,
                "source_document_id": str(field.document_id),
                "page_number": field.page_number,
                "reviewer_name": payload.reviewer_name.strip(),
                "compliance_results_invalidated": True,
            },
        )
    )
    db.commit()
    db.refresh(field)
    return ExtractedFieldRead.model_validate(field)


@router.post("/{supplier_id}/approve", response_model=DecisionResponse)
def approve_supplier(
    supplier_id: uuid.UUID,
    payload: ApprovalRequest,
    db: Session = Depends(get_db),
) -> DecisionResponse:
    supplier = _get_review_supplier(db, supplier_id)
    if supplier.status == SupplierStatus.REJECTED:
        raise HTTPException(status_code=409, detail="A rejected supplier cannot be approved.")
    if supplier.status == SupplierStatus.APPROVED:
        return DecisionResponse(
            supplier_id=supplier.id,
            status=supplier.status,
            message="Supplier was already approved.",
            erp_supplier_id=supplier.erp_supplier_id,
            decided_at=supplier.decided_at or datetime.now(UTC),
        )

    results = persist_compliance_results(db, supplier, evaluate_compliance(supplier))
    record_compliance_checks([result.status.value for result in results])
    if not approval_ready(results):
        db.commit()
        raise HTTPException(
            status_code=409,
            detail="All compliance checks must pass before approval.",
        )

    erp_result = get_mock_erp_service().create_supplier(supplier)
    supplier.status = SupplierStatus.APPROVED
    supplier.decision_reason = "Approved after human review."
    supplier.decided_at = erp_result.completed_at
    supplier.erp_supplier_id = erp_result.supplier_id
    db.add(
        AuditEvent(
            supplier_id=supplier.id,
            action="erp.supplier.created",
            entity_type="supplier",
            entity_id=erp_result.supplier_id,
            details={"status": erp_result.status},
        )
    )
    db.add(
        AuditEvent(
            supplier_id=supplier.id,
            action="supplier.approved",
            entity_type="supplier",
            entity_id=str(supplier.id),
            details={
                "reviewer_name": payload.reviewer_name.strip(),
                "erp_supplier_id": erp_result.supplier_id,
            },
        )
    )
    db.commit()
    record_supplier_decision("approved")
    return DecisionResponse(
        supplier_id=supplier.id,
        status=supplier.status,
        message="Supplier approved and created in the mock ERP.",
        erp_supplier_id=supplier.erp_supplier_id,
        decided_at=supplier.decided_at,
    )


@router.post("/{supplier_id}/reject", response_model=DecisionResponse)
def reject_supplier(
    supplier_id: uuid.UUID,
    payload: RejectionRequest,
    db: Session = Depends(get_db),
) -> DecisionResponse:
    supplier = _get_review_supplier(db, supplier_id)
    if supplier.status == SupplierStatus.APPROVED:
        raise HTTPException(status_code=409, detail="An approved supplier cannot be rejected.")
    if supplier.status == SupplierStatus.REJECTED:
        return DecisionResponse(
            supplier_id=supplier.id,
            status=supplier.status,
            message="Supplier was already rejected.",
            erp_supplier_id=None,
            decided_at=supplier.decided_at or datetime.now(UTC),
        )

    decided_at = datetime.now(UTC)
    supplier.status = SupplierStatus.REJECTED
    supplier.decision_reason = payload.reason.strip()
    supplier.decided_at = decided_at
    supplier.erp_supplier_id = None
    db.add(
        AuditEvent(
            supplier_id=supplier.id,
            action="supplier.rejected",
            entity_type="supplier",
            entity_id=str(supplier.id),
            details={
                "reason": supplier.decision_reason,
                "reviewer_name": payload.reviewer_name.strip(),
            },
        )
    )
    db.commit()
    record_supplier_decision("rejected")
    return DecisionResponse(
        supplier_id=supplier.id,
        status=supplier.status,
        message="Supplier rejected with an audited reason.",
        erp_supplier_id=None,
        decided_at=decided_at,
    )
