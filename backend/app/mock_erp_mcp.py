"""Stateless MCP JSON-RPC boundary for the demo ERP supplier master."""

import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.database import SessionLocal
from app.services.erp_tools import ErpToolFailure, TOOL_NAMES, execute_erp_tool

app = FastAPI(title="VendorLens Mock ERP MCP")

TOOL_DESCRIPTIONS = {
    "validate_supplier_record": "Validate required fields, ERP mappings, and duplicate master data before approval.",
    "create_supplier_record": "Create an idempotent supplier master record after explicit reviewer approval.",
    "get_supplier_record": "Retrieve one created ERP supplier record by ERP supplier ID.",
    "list_supplier_records": "List supplier master records created in the mock ERP.",
}


def _tool_schema(name: str) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    if name in {"validate_supplier_record", "create_supplier_record"}:
        properties.update({"payload": {"type": "object"}, "idempotency_key": {"type": "string"}, "source_supplier_id": {"type": "string", "format": "uuid"}})
        required.extend(["payload", "idempotency_key", "source_supplier_id"])
    elif name == "get_supplier_record":
        properties.update({"erp_supplier_id": {"type": "string"}, "source_supplier_id": {"type": "string", "format": "uuid"}})
        required.append("erp_supplier_id")
    return {"name": name, "description": TOOL_DESCRIPTIONS[name], "inputSchema": {"type": "object", "properties": properties, "required": required}}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy", "service": "mock-erp-mcp"}


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> JSONResponse:
    message = await request.json()
    request_id = message.get("id")
    method = message.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "vendorlens-mock-erp", "version": "1.0.0"}}
    elif method == "tools/list":
        result = {"tools": [_tool_schema(name) for name in TOOL_NAMES]}
    elif method == "tools/call":
        params = message.get("params") or {}
        try:
            with SessionLocal() as db:
                output = execute_erp_tool(db, str(params.get("name")), params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(output)}], "structuredContent": output, "isError": False}
        except ErpToolFailure as exc:
            result = {"content": [{"type": "text", "text": exc.message}], "structuredContent": {"code": exc.code, "message": exc.message, "retryable": exc.retryable, "details": exc.details or []}, "isError": True}
        except Exception:
            result = {"content": [{"type": "text", "text": "The mock ERP tool could not complete the request."}], "structuredContent": {"code": "ERP_UNAVAILABLE", "message": "The mock ERP tool could not complete the request.", "retryable": True, "details": []}, "isError": True}
    else:
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}, status_code=400)
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result}, headers={"MCP-Protocol-Version": "2025-06-18"})
