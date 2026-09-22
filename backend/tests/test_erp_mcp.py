import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.database import Base
from app.models import ErpSupplierRecord, ErpToolAttempt
from app.mock_erp_mcp import app as mock_erp_app
from app.services.erp_mcp_client import ErpMcpClient
from app.services.erp_tools import ErpToolFailure, execute_erp_tool


def database() -> tuple[object, Session]:
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def payload(reference: str = "SUP-ABC12345") -> dict:
    return {
        "supplier_reference": reference,
        "legal_name": "ERP Tool Demo Pvt Ltd",
        "registered_address": "Hyderabad",
        "country": "India",
        "tax_reference": f"PAN-{reference}",
        "contact_name": "Demo Contact",
        "contact_email": "erp@example.com",
        "bank_account_number": f"BANK-{reference}",
        "bank_ifsc": "DEMO0001234",
        "category": "TECH",
        "subcategory": "TECH-CYB",
    }


def arguments(source_id: uuid.UUID, reference: str = "SUP-ABC12345") -> dict:
    return {"payload": payload(reference), "idempotency_key": reference, "source_supplier_id": str(source_id)}


def test_mcp_service_advertises_erp_tools() -> None:
    response = TestClient(mock_erp_app).post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": "tools", "method": "tools/list", "params": {}},
    )

    assert response.status_code == 200
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert names == {
        "validate_supplier_record",
        "create_supplier_record",
        "get_supplier_record",
        "list_supplier_records",
    }


def test_create_is_idempotent_and_retrievable() -> None:
    engine, db = database()
    try:
        source_id = uuid.uuid4()
        first = execute_erp_tool(db, "create_supplier_record", arguments(source_id))
        second = execute_erp_tool(db, "create_supplier_record", arguments(source_id))
        retrieved = execute_erp_tool(db, "get_supplier_record", {"erp_supplier_id": first["erp_supplier_id"], "source_supplier_id": str(source_id)})

        assert first["created"] is True
        assert second["created"] is False
        assert second["idempotent_replay"] is True
        assert second["erp_supplier_id"] == first["erp_supplier_id"]
        assert retrieved["payload"] == payload()
        assert db.scalar(select(func.count(ErpSupplierRecord.id))) == 1
    finally:
        db.close()
        engine.dispose()


def test_duplicate_tax_and_bank_are_actionable_erp_validation_errors() -> None:
    engine, db = database()
    try:
        execute_erp_tool(db, "create_supplier_record", arguments(uuid.uuid4()))
        duplicate = arguments(uuid.uuid4(), "SUP-DIFFERENT")
        duplicate["payload"]["tax_reference"] = payload()["tax_reference"]
        duplicate["payload"]["bank_account_number"] = payload()["bank_account_number"]

        result = execute_erp_tool(db, "validate_supplier_record", duplicate)

        assert result["valid"] is False
        assert {item["code"] for item in result["errors"]} == {"DUPLICATE_TAX_REFERENCE", "DUPLICATE_BANK_ACCOUNT"}
    finally:
        db.close()
        engine.dispose()


def test_tool_attempt_audit_does_not_store_sensitive_values() -> None:
    engine, db = database()
    try:
        source_id = uuid.uuid4()
        execute_erp_tool(db, "validate_supplier_record", arguments(source_id))
        attempt = db.scalar(select(ErpToolAttempt))

        assert attempt is not None
        assert attempt.request_summary["payload_fields"]
        serialized = str(attempt.request_summary)
        assert payload()["tax_reference"] not in serialized
        assert payload()["bank_account_number"] not in serialized
    finally:
        db.close()
        engine.dispose()


def test_unavailable_remote_mcp_is_retryable_and_does_not_create_a_record() -> None:
    engine, db = database()
    try:
        client = ErpMcpClient(Settings(mock_erp_mcp_url="http://127.0.0.1:1/mcp", mock_erp_timeout_seconds=1))
        with pytest.raises(ErpToolFailure) as failure:
            client.call(db, "create_supplier_record", arguments(uuid.uuid4()))

        assert failure.value.code == "ERP_UNAVAILABLE"
        assert failure.value.retryable is True
        assert db.scalar(select(func.count(ErpSupplierRecord.id))) == 0
    finally:
        db.close()
        engine.dispose()
