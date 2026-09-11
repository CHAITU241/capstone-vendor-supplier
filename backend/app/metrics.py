"""Prometheus metrics for the VendorLens demo.

Metric labels intentionally describe bounded dimensions such as route,
operation, model, and status. Supplier IDs, filenames, questions, and other
unbounded user data are never labels.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Iterator

from prometheus_client import Counter, Gauge, Histogram, make_asgi_app


HTTP_REQUESTS = Counter(
    "vendorlens_http_requests_total",
    "Total HTTP requests handled by the VendorLens API.",
    ("method", "route", "status"),
)
HTTP_REQUEST_DURATION = Histogram(
    "vendorlens_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route"),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "vendorlens_http_requests_in_progress",
    "Current number of in-progress HTTP requests.",
)

AI_CALLS = Counter(
    "vendorlens_ai_calls_total",
    "AI calls grouped by operation, model, and outcome.",
    ("operation", "model", "status"),
)
AI_CALL_DURATION = Histogram(
    "vendorlens_ai_call_duration_seconds",
    "AI call duration in seconds.",
    ("operation", "model"),
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)
AI_TOKENS = Counter(
    "vendorlens_ai_tokens_total",
    "AI tokens reported by the provider.",
    ("operation", "direction"),
)

PROCESSING_RUNS = Counter(
    "vendorlens_processing_runs_total",
    "Supplier document processing runs by outcome.",
    ("status",),
)
RAG_QUESTIONS = Counter(
    "vendorlens_rag_questions_total",
    "Supplier-scoped questions grouped by whether evidence was found.",
    ("information_found",),
)
RAG_RETRIEVED_CHUNKS = Histogram(
    "vendorlens_rag_retrieved_chunks",
    "Number of chunks retrieved for a supplier question.",
    buckets=(0, 1, 2, 3, 4, 5, 8, 12),
)
COMPLIANCE_CHECKS = Counter(
    "vendorlens_compliance_checks_total",
    "Persisted deterministic compliance checks by status.",
    ("status",),
)
SUPPLIER_DECISIONS = Counter(
    "vendorlens_supplier_decisions_total",
    "Human-confirmed supplier decisions.",
    ("decision",),
)

DEPENDENCY_UP = Gauge(
    "vendorlens_dependency_up",
    "Whether a VendorLens dependency is available (1=yes, 0=no).",
    ("dependency",),
)


@dataclass
class AICallObservation:
    input_tokens: int = 0
    output_tokens: int = 0


@contextmanager
def observe_ai_call(operation: str, model: str) -> Iterator[AICallObservation]:
    """Record AI duration, status, and token usage without changing behavior."""

    observation = AICallObservation()
    started = perf_counter()
    status = "success"
    try:
        yield observation
    except Exception:
        status = "error"
        raise
    finally:
        AI_CALLS.labels(operation=operation, model=model, status=status).inc()
        AI_CALL_DURATION.labels(operation=operation, model=model).observe(
            perf_counter() - started
        )
        if observation.input_tokens:
            AI_TOKENS.labels(operation=operation, direction="input").inc(
                observation.input_tokens
            )
        if observation.output_tokens:
            AI_TOKENS.labels(operation=operation, direction="output").inc(
                observation.output_tokens
            )


def record_processing(status: str) -> None:
    PROCESSING_RUNS.labels(status=status).inc()


def record_rag_question(information_found: bool, retrieved_count: int) -> None:
    RAG_QUESTIONS.labels(information_found=str(information_found).lower()).inc()
    RAG_RETRIEVED_CHUNKS.observe(retrieved_count)


def record_compliance_checks(statuses: list[str]) -> None:
    for status in statuses:
        COMPLIANCE_CHECKS.labels(status=status).inc()


def record_supplier_decision(decision: str) -> None:
    SUPPLIER_DECISIONS.labels(decision=decision).inc()


def set_dependency_status(dependency: str, is_up: bool) -> None:
    DEPENDENCY_UP.labels(dependency=dependency).set(1 if is_up else 0)


def metrics_asgi_app():
    """Return the official Prometheus ASGI exposition application."""

    return make_asgi_app()
