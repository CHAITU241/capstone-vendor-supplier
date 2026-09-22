import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import ErpSupplierRecord, ErpToolAttempt


TOOL_NAMES = (
    "validate_supplier_record",
    "create_supplier_record",
    "get_supplier_record",
    "list_supplier_records",
)


@dataclass
class ErpToolFailure(Exception):
    code: str
    message: str
    retryable: bool = False
    details: list[dict[str, Any]] | None = None

    def __str__(self) -> str:
        return self.message


def _value(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    return "" if value is None else str(value).strip()


def validate_supplier_record(db: Session, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    required = {
        "supplier_reference": "Supplier reference",
        "legal_name": "Legal name",
        "country": "Country",
        "tax_reference": "Tax reference",
        "bank_account_number": "Bank account number",
        "bank_ifsc": "Bank IFSC",
        "category": "Category",
        "subcategory": "Subcategory",
    }
    for field, label in required.items():
        if not _value(payload, field):
            errors.append({"field": field, "code": "REQUIRED_FIELD", "message": f"{label} is required by the ERP."})

    if _value(payload, "country").casefold() != "india":
        errors.append({"field": "country", "code": "UNSUPPORTED_COUNTRY", "message": "The mock ERP accepts India-based suppliers only."})
    category, subcategory = _value(payload, "category"), _value(payload, "subcategory")
    if category and subcategory and not subcategory.startswith(f"{category}-"):
        errors.append({"field": "subcategory", "code": "INVALID_CATEGORY_MAPPING", "message": "The subcategory does not map to the selected ERP category."})
    if _value(payload, "bank_ifsc") and len(_value(payload, "bank_ifsc")) < 6:
        errors.append({"field": "bank_ifsc", "code": "INVALID_IFSC", "message": "Bank IFSC is too short for the ERP master record."})

    existing_key = db.scalar(select(ErpSupplierRecord).where(ErpSupplierRecord.idempotency_key == idempotency_key))
    if existing_key:
        return {"valid": True, "errors": [], "warnings": [], "existing_erp_supplier_id": existing_key.erp_supplier_id, "idempotent_replay": True}

    tax_reference, bank_account = _value(payload, "tax_reference"), _value(payload, "bank_account_number")
    if tax_reference or bank_account:
        duplicates = db.scalars(select(ErpSupplierRecord).where(or_(
            ErpSupplierRecord.tax_reference == tax_reference,
            ErpSupplierRecord.bank_account_number == bank_account,
        ))).all()
        for record in duplicates:
            if tax_reference and record.tax_reference == tax_reference:
                errors.append({"field": "tax_reference", "code": "DUPLICATE_TAX_REFERENCE", "message": f"This tax reference already belongs to {record.erp_supplier_id}."})
            if bank_account and record.bank_account_number == bank_account:
                errors.append({"field": "bank_account_number", "code": "DUPLICATE_BANK_ACCOUNT", "message": f"This bank account already belongs to {record.erp_supplier_id}."})

    for optional in ("registered_address", "contact_name", "payment_terms"):
        if not _value(payload, optional):
            warnings.append({"field": optional, "code": "OPTIONAL_FIELD_EMPTY", "message": f"{optional.replace('_', ' ').title()} is not populated."})
    return {"valid": not errors, "errors": errors, "warnings": warnings, "existing_erp_supplier_id": None, "idempotent_replay": False}


def _record_dict(record: ErpSupplierRecord) -> dict[str, Any]:
    return {
        "erp_supplier_id": record.erp_supplier_id,
        "supplier_reference": record.payload.get("supplier_reference"),
        "source_supplier_id": str(record.source_supplier_id),
        "legal_name": record.legal_name,
        "tax_reference": record.tax_reference,
        "category": record.category,
        "subcategory": record.subcategory,
        "status": record.status,
        "payload": record.payload,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def create_supplier_record(db: Session, payload: dict[str, Any], idempotency_key: str, source_supplier_id: uuid.UUID) -> dict[str, Any]:
    existing = db.scalar(select(ErpSupplierRecord).where(ErpSupplierRecord.idempotency_key == idempotency_key))
    if existing:
        return {**_record_dict(existing), "created": False, "idempotent_replay": True}
    validation = validate_supplier_record(db, payload, idempotency_key)
    if not validation["valid"]:
        raise ErpToolFailure("ERP_VALIDATION_FAILED", "The proposed supplier record failed ERP validation.", details=validation["errors"])
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:10].upper()
    record = ErpSupplierRecord(
        erp_supplier_id=f"ERP-{digest}", idempotency_key=idempotency_key,
        source_supplier_id=source_supplier_id, legal_name=_value(payload, "legal_name"),
        tax_reference=_value(payload, "tax_reference"), bank_account_number=_value(payload, "bank_account_number"),
        category=_value(payload, "category"), subcategory=_value(payload, "subcategory"),
        status="active", payload=payload,
    )
    db.add(record)
    db.flush()
    return {**_record_dict(record), "created": True, "idempotent_replay": False}


def get_supplier_record(db: Session, erp_supplier_id: str) -> dict[str, Any]:
    record = db.scalar(select(ErpSupplierRecord).where(ErpSupplierRecord.erp_supplier_id == erp_supplier_id))
    if not record:
        raise ErpToolFailure("ERP_RECORD_NOT_FOUND", "The ERP supplier record was not found.")
    return _record_dict(record)


def list_supplier_records(db: Session) -> dict[str, Any]:
    records = db.scalars(select(ErpSupplierRecord).order_by(ErpSupplierRecord.created_at.desc())).all()
    return {"records": [_record_dict(record) for record in records], "count": len(records)}


def execute_erp_tool(db: Session, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name not in TOOL_NAMES:
        raise ErpToolFailure("UNKNOWN_TOOL", f"Unknown ERP tool: {tool_name}")
    supplier_id = uuid.UUID(str(arguments.get("source_supplier_id") or uuid.UUID(int=0)))
    started = time.perf_counter()
    attempt_number = int(db.scalar(select(func.count(ErpToolAttempt.id)).where(
        ErpToolAttempt.supplier_id == supplier_id,
        ErpToolAttempt.operation == tool_name,
    )) or 0) + 1
    request_summary = {
        "idempotency_key": arguments.get("idempotency_key"),
        "erp_supplier_id": arguments.get("erp_supplier_id"),
        "payload_fields": sorted((arguments.get("payload") or {}).keys()),
    }
    try:
        if tool_name == "validate_supplier_record":
            result = validate_supplier_record(db, arguments["payload"], arguments["idempotency_key"])
        elif tool_name == "create_supplier_record":
            result = create_supplier_record(db, arguments["payload"], arguments["idempotency_key"], supplier_id)
        elif tool_name == "get_supplier_record":
            result = get_supplier_record(db, arguments["erp_supplier_id"])
        else:
            result = list_supplier_records(db)
        db.add(ErpToolAttempt(
            supplier_id=supplier_id, operation=tool_name, status="succeeded", attempt_number=attempt_number,
            latency_ms=round((time.perf_counter() - started) * 1000), request_summary=request_summary,
            response_summary={"valid": result.get("valid"), "erp_supplier_id": result.get("erp_supplier_id"), "record_count": result.get("count")},
        ))
        db.commit()
        return result
    except ErpToolFailure as exc:
        db.rollback()
        db.add(ErpToolAttempt(
            supplier_id=supplier_id, operation=tool_name, status="failed", attempt_number=attempt_number,
            latency_ms=round((time.perf_counter() - started) * 1000), error_code=exc.code,
            error_message=exc.message, request_summary=request_summary,
            response_summary={"detail_count": len(exc.details or [])},
        ))
        db.commit()
        raise
