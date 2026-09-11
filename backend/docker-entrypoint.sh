#!/bin/sh
set -eu

echo "Applying database migrations..."
python -m alembic upgrade head

echo "Starting VendorLens API..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
