"""Read-only Langfuse summaries for the authenticated admin workspace."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
import re
from typing import Any

from app.config import Settings
from app.services.tracing import get_langfuse_tracer

logger = logging.getLogger(__name__)


def _safe_diagnostic(exc: Exception, settings: Settings) -> str:
    """Expose temporary admin-only diagnostics without leaking credentials."""

    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
    body = getattr(exc, "body", None)
    if body is None and response is not None:
        try:
            body = response.text
        except Exception:
            body = None
    if body is not None and not isinstance(body, str):
        try:
            body = json.dumps(body, default=str)
        except Exception:
            body = repr(body)
    message = str(body or exc)
    secrets = [settings.langfuse_public_key or ""]
    if settings.langfuse_secret_key:
        secrets.append(settings.langfuse_secret_key.get_secret_value())
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    message = re.sub(
        r"(?i)(authorization|secret[_ -]?key|public[_ -]?key)(\s*[:=]\s*)([^\s,;}]+)",
        r"\1\2[redacted]",
        message,
    )
    message = " ".join(message.split())[:500]
    parts = [type(exc).__name__]
    if status is not None:
        parts.append(f"HTTP {status}")
    if message:
        parts.append(message)
    return " · ".join(parts)


@dataclass(frozen=True)
class LangfuseCostGroup:
    model: str
    cost_usd: float
    observations: int


@dataclass(frozen=True)
class LangfuseScoreGroup:
    name: str
    average: float
    count: int


@dataclass(frozen=True)
class LangfuseMetricsSnapshot:
    available: bool = False
    trace_available: bool = False
    usage_available: bool = False
    scores_available: bool = False
    error: str | None = None
    trace_count: int = 0
    observation_count: int = 0
    score_count: int = 0
    total_cost_usd: float = 0
    cost_by_model: list[LangfuseCostGroup] = field(default_factory=list)
    scores: list[LangfuseScoreGroup] = field(default_factory=list)


def _configured(settings: Settings) -> bool:
    secret = (
        settings.langfuse_secret_key.get_secret_value().strip()
        if settings.langfuse_secret_key else ""
    )
    return bool(
        settings.langfuse_enabled
        and (settings.langfuse_public_key or "").strip()
        and secret
    )


def _langfuse_api() -> Any | None:
    """Reuse the SDK client that is already successfully sending application traces."""

    client = get_langfuse_tracer().client
    return client.api if client is not None else None


def fetch_langfuse_metrics(
    settings: Settings,
    cutoff: datetime | None,
    *,
    api: Any | None = None,
) -> LangfuseMetricsSnapshot:
    """Return privacy-safe metrics without requesting trace input or output fields.

    Trace, observation, and score endpoints are intentionally isolated. A version or
    availability problem in one Langfuse endpoint must not blank the other metrics.
    """

    if not _configured(settings):
        return LangfuseMetricsSnapshot()

    api = api or _langfuse_api()
    if api is None:
        return LangfuseMetricsSnapshot(
            error="The Langfuse SDK connection is unavailable. Tracing will retry automatically."
        )

    errors: list[str] = []
    trace_available = False
    usage_available = False
    scores_available = False
    trace_count = 0
    observations: list[Any] = []
    score_rows: list[Any] = []

    try:
        traces = api.trace.list(
            page=1,
            limit=1,
            from_timestamp=cutoff,
            fields="core",
        )
        trace_count = int(traces.meta.total_items)
        trace_available = True
    except Exception as exc:  # pragma: no cover - depends on external Langfuse availability
        logger.warning("Langfuse trace metrics could not be loaded.", exc_info=True)
        errors.append(f"traces [{_safe_diagnostic(exc, settings)}]")

    try:
        cursor: str | None = None
        while True:
            page = api.observations.get_many(
                limit=1000,
                cursor=cursor,
                fields="basic,usage,model",
                from_start_time=cutoff,
            )
            observations.extend(page.data)
            cursor = page.meta.cursor
            if not cursor:
                break
        usage_available = True
    except Exception as exc:  # pragma: no cover - depends on external Langfuse availability
        logger.warning("Langfuse usage metrics could not be loaded.", exc_info=True)
        observations = []
        errors.append(f"cost and observations [{_safe_diagnostic(exc, settings)}]")

    try:
        cursor = None
        while True:
            page = api.scores_v3.get_many_v3(
                limit=100,
                cursor=cursor,
                from_timestamp=cutoff,
            )
            score_rows.extend(page.data)
            cursor = page.meta.cursor
            if not cursor:
                break
        scores_available = True
    except Exception as exc:  # pragma: no cover - depends on external Langfuse availability
        logger.warning("Langfuse score metrics could not be loaded.", exc_info=True)
        score_rows = []
        errors.append(f"scores [{_safe_diagnostic(exc, settings)}]")

    model_costs: dict[str, float] = defaultdict(float)
    model_counts: dict[str, int] = defaultdict(int)
    for observation in observations:
        model = observation.provided_model_name
        if not model:
            continue
        model_counts[str(model)] += 1
        model_costs[str(model)] += float(observation.total_cost or 0)

    if usage_available and observations and not model_counts:
        errors.append(
            f"cost attribution [received {len(observations)} observations, but Langfuse returned "
            "no provided model names in the requested model fields]"
        )

    score_values: dict[str, list[float]] = defaultdict(list)
    for score in score_rows:
        value = score.value
        if isinstance(value, bool):
            score_values[str(score.name or "Unnamed score")].append(float(value))
        elif isinstance(value, (int, float)):
            score_values[str(score.name or "Unnamed score")].append(float(value))

    available = trace_available or usage_available or scores_available
    error = (
        f"Some Langfuse metrics could not be loaded: {', '.join(errors)}."
        if errors and available else
        "Langfuse metrics are temporarily unavailable. Tracing remains unaffected."
        if errors else None
    )
    return LangfuseMetricsSnapshot(
        available=available,
        trace_available=trace_available,
        usage_available=usage_available,
        scores_available=scores_available,
        error=error,
        trace_count=trace_count,
        observation_count=len(observations),
        score_count=len(score_rows),
        total_cost_usd=round(sum(model_costs.values()), 8),
        cost_by_model=[
            LangfuseCostGroup(
                model=model,
                cost_usd=round(model_costs[model], 8),
                observations=model_counts[model],
            )
            for model in sorted(model_counts, key=lambda item: (-model_costs[item], item))
        ],
        scores=[
            LangfuseScoreGroup(
                name=name,
                average=round(sum(values) / len(values), 4),
                count=len(values),
            )
            for name, values in sorted(score_values.items(), key=lambda item: (-len(item[1]), item[0]))
        ],
    )
