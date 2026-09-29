"""Read-only Langfuse summaries for the authenticated admin workspace."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


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
    error: str | None = None
    trace_count: int = 0
    observation_count: int = 0
    score_count: int = 0
    total_cost_usd: float = 0
    cost_by_model: list[LangfuseCostGroup] = field(default_factory=list)
    scores: list[LangfuseScoreGroup] = field(default_factory=list)


def _page_data(
    client: httpx.Client,
    path: str,
    params: dict[str, Any],
    *,
    cursor_pagination: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch all cursor pages while retaining the first response metadata."""

    rows: list[dict[str, Any]] = []
    first_meta: dict[str, Any] = {}
    cursor: str | None = None
    while True:
        request_params = {**params}
        if cursor:
            request_params["cursor"] = cursor
        response = client.get(path, params=request_params)
        response.raise_for_status()
        payload = response.json()
        if not first_meta:
            first_meta = payload.get("meta") or {}
        rows.extend(payload.get("data") or [])
        if not cursor_pagination:
            break
        cursor = (payload.get("meta") or {}).get("cursor")
        if not cursor:
            break
    return rows, first_meta


def fetch_langfuse_metrics(
    settings: Settings,
    cutoff: datetime | None,
) -> LangfuseMetricsSnapshot:
    """Return privacy-safe project metrics without requesting trace input/output."""

    secret = (
        settings.langfuse_secret_key.get_secret_value().strip()
        if settings.langfuse_secret_key else ""
    )
    public = (settings.langfuse_public_key or "").strip()
    if not settings.langfuse_enabled or not public or not secret:
        return LangfuseMetricsSnapshot()

    timestamp_params = {"fromTimestamp": cutoff.isoformat()} if cutoff else {}
    observation_time = {"fromStartTime": cutoff.isoformat()} if cutoff else {}
    base_url = settings.langfuse_base_url.rstrip("/") + "/"

    try:
        with httpx.Client(
            base_url=base_url,
            auth=(public, secret),
            timeout=settings.langfuse_metrics_timeout_seconds,
            headers={"Accept": "application/json"},
        ) as client:
            trace_response = client.get(
                "api/public/traces",
                params={"limit": 1, "fields": "core", **timestamp_params},
            )
            trace_response.raise_for_status()
            trace_payload = trace_response.json()
            trace_count = int((trace_payload.get("meta") or {}).get("totalItems") or 0)

            observations, _ = _page_data(
                client,
                "api/public/v2/observations",
                {
                    "limit": 1000,
                    "fields": "basic,usage,model",
                    **observation_time,
                },
                cursor_pagination=True,
            )
            score_rows, _ = _page_data(
                client,
                "api/public/v3/scores",
                {"limit": 100, **timestamp_params},
                cursor_pagination=True,
            )
    except Exception:  # pragma: no cover - depends on external Langfuse availability
        logger.warning("Langfuse admin metrics could not be loaded.", exc_info=True)
        return LangfuseMetricsSnapshot(
            error="Langfuse metrics are temporarily unavailable. Tracing remains unaffected."
        )

    model_costs: dict[str, float] = defaultdict(float)
    model_counts: dict[str, int] = defaultdict(int)
    for observation in observations:
        model = observation.get("providedModelName")
        if not model:
            continue
        model_counts[str(model)] += 1
        model_costs[str(model)] += float(observation.get("totalCost") or 0)

    score_values: dict[str, list[float]] = defaultdict(list)
    for score in score_rows:
        value = score.get("value")
        if isinstance(value, bool):
            score_values[str(score.get("name") or "Unnamed score")].append(float(value))
        elif isinstance(value, (int, float)):
            score_values[str(score.get("name") or "Unnamed score")].append(float(value))

    return LangfuseMetricsSnapshot(
        available=True,
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
