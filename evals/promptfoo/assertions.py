"""Deterministic Promptfoo assertions for VendorLens API responses."""

from __future__ import annotations

import json
from typing import Any


def _payload(output: str) -> dict[str, Any] | None:
    try:
        value = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _result(passed: bool, checks: dict[str, bool], reasons: list[str]) -> dict[str, Any]:
    score = sum(checks.values()) / len(checks) if checks else float(passed)
    return {
        "pass": passed,
        "score": round(score, 3),
        "reason": "All checks passed." if passed else "; ".join(reasons),
        "namedScores": {name: 1.0 if value else 0.0 for name, value in checks.items()},
    }


def check_rag(output: str, context: dict[str, Any]) -> dict[str, Any]:
    """Check grounded answer, source citation, not-found guard, and latency."""

    variables = context.get("vars", {}) if isinstance(context, dict) else {}
    payload = _payload(output)
    checks: dict[str, bool] = {}
    reasons: list[str] = []
    if payload is None:
        return _result(False, {"valid_json": False}, ["Provider output was not valid JSON."])

    answer = str(payload.get("answer", ""))
    answer_lower = answer.casefold()
    expected_found = variables.get("expected_information_found")
    if isinstance(expected_found, str):
        expected_found = expected_found.casefold() == "true"
    checks["information_found"] = payload.get("information_found") is expected_found
    if not checks["information_found"]:
        reasons.append(f"Expected information_found={expected_found!r}.")

    terms = _items(variables.get("expected_terms"))
    checks["expected_terms"] = bool(terms) and all(term.casefold() in answer_lower for term in terms)
    if not checks["expected_terms"]:
        reasons.append("The answer did not contain every expected answer term.")

    citations = payload.get("citations") if isinstance(payload.get("citations"), list) else []
    citation_sources = {
        str(citation.get("filename", ""))
        for citation in citations
        if isinstance(citation, dict)
    }
    expected_sources = set(_items(variables.get("expected_sources")))
    if expected_sources:
        checks["citation_source"] = bool(citation_sources & expected_sources)
        if not checks["citation_source"]:
            reasons.append("No citation came from an expected source document.")
    else:
        checks["not_found_has_no_citations"] = len(citations) == 0
        if not checks["not_found_has_no_citations"]:
            reasons.append("A not-found answer returned citations.")

    forbidden_terms = _items(variables.get("forbidden_terms"))
    checks["supplier_isolation"] = not any(term.casefold() in answer_lower for term in forbidden_terms)
    if not checks["supplier_isolation"]:
        reasons.append("The answer contains a forbidden cross-supplier term.")

    run = payload.get("run") if isinstance(payload.get("run"), dict) else {}
    latency = run.get("latency_ms")
    max_latency = variables.get("max_latency_ms", 5000)
    try:
        checks["latency"] = isinstance(latency, int) and latency <= int(max_latency)
    except (TypeError, ValueError):
        checks["latency"] = False
    if not checks["latency"]:
        reasons.append(f"Latency exceeded {max_latency} ms or was missing.")

    return _result(all(checks.values()), checks, reasons)


def check_assistant(output: str, context: dict[str, Any]) -> dict[str, Any]:
    """Check global assistant guidance and sensitive-data boundaries."""

    variables = context.get("vars", {}) if isinstance(context, dict) else {}
    payload = _payload(output)
    if payload is None:
        return _result(False, {"valid_json": False}, ["Provider output was not valid JSON."])

    answer = str(payload.get("answer", ""))
    answer_lower = answer.casefold()
    checks: dict[str, bool] = {}
    reasons: list[str] = []

    terms = _items(variables.get("expected_terms"))
    checks["expected_guidance"] = bool(terms) and all(term.casefold() in answer_lower for term in terms)
    if not checks["expected_guidance"]:
        reasons.append("The assistant did not include every required guidance term.")

    forbidden_terms = _items(variables.get("forbidden_terms"))
    checks["boundary"] = not any(term.casefold() in answer_lower for term in forbidden_terms)
    if not checks["boundary"]:
        reasons.append("The assistant response contained a forbidden sensitive or unsupported claim.")

    run = payload.get("run") if isinstance(payload.get("run"), dict) else {}
    latency = run.get("latency_ms")
    max_latency = variables.get("max_latency_ms", 5000)
    try:
        checks["latency"] = isinstance(latency, int) and latency <= int(max_latency)
    except (TypeError, ValueError):
        checks["latency"] = False
    if not checks["latency"]:
        reasons.append(f"Latency exceeded {max_latency} ms or was missing.")

    return _result(all(checks.values()), checks, reasons)
