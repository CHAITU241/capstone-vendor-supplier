"""Promptfoo provider entry point for supplier-scoped RAG tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_provider import call_api as _call_api  # noqa: E402


def call_api(prompt, options, context):
    config = dict(options.get("config") or {})
    config["mode"] = "rag"
    return _call_api(prompt, {"config": config}, context)
