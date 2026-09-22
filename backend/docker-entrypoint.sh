#!/bin/sh
set -eu

if [ "${SERVICE_ROLE:-api}" = "mock-erp-mcp" ]; then
  echo "Starting mock ERP MCP server..."
  exec python -m uvicorn app.mock_erp_mcp:app --host 0.0.0.0 --port 8010
fi

echo "Applying database migrations..."
python -m alembic upgrade head

echo "Starting VendorLens API..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
