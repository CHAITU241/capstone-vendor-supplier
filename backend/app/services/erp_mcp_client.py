import uuid
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.services.erp_tools import ErpToolFailure, execute_erp_tool


class ErpMcpClient:
    """Calls the deployed MCP service, with an in-process transport for tests/local use."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def call(self, db: Session, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.mock_erp_mcp_url:
            return execute_erp_tool(db, tool_name, arguments)
        request_id = str(uuid.uuid4())
        try:
            with httpx.Client(trust_env=False, timeout=self.settings.mock_erp_timeout_seconds) as client:
                response = client.post(
                    self.settings.mock_erp_mcp_url,
                    json={"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}},
                    headers={"Accept": "application/json", "MCP-Protocol-Version": "2025-06-18"},
                )
            response.raise_for_status()
            result = response.json()["result"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ErpToolFailure("ERP_UNAVAILABLE", "The mock ERP is temporarily unavailable. No supplier record was created; retry is safe.", retryable=True) from exc
        structured = result.get("structuredContent") or {}
        if result.get("isError"):
            raise ErpToolFailure(
                str(structured.get("code") or "ERP_TOOL_FAILED"),
                str(structured.get("message") or "The mock ERP tool failed."),
                bool(structured.get("retryable")),
                structured.get("details") or [],
            )
        return structured


def supplier_idempotency_key(supplier_id: uuid.UUID) -> str:
    return f"SUP-{supplier_id.hex[:8].upper()}"
