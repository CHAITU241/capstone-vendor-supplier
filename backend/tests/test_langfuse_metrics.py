from datetime import datetime, timezone

import httpx

from app.config import Settings
from app.services.langfuse_metrics import fetch_langfuse_metrics


class _FakeClient:
    responses: dict[str, list[dict]] = {}

    def __init__(self, **_):
        self.calls: dict[str, int] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def get(self, path, params=None):
        index = self.calls.get(path, 0)
        self.calls[path] = index + 1
        payload = self.responses[path][index]
        return httpx.Response(200, json=payload, request=httpx.Request("GET", f"https://example.test/{path}"))


def _settings() -> Settings:
    return Settings(
        langfuse_enabled=True,
        langfuse_public_key="pk-test",
        langfuse_secret_key="sk-test",
        langfuse_base_url="https://example.test",
    )


def test_langfuse_metrics_group_cost_and_scores(monkeypatch):
    _FakeClient.responses = {
        "api/public/traces": [{"data": [], "meta": {"totalItems": 4}}],
        "api/public/v2/observations": [{
            "data": [
                {"providedModelName": "gpt-4o-mini", "totalCost": 0.003},
                {"providedModelName": "gpt-4o-mini", "totalCost": 0.002},
                {"providedModelName": "text-embedding-3-small", "totalCost": 0.0001},
                {"providedModelName": None, "totalCost": None},
            ],
            "meta": {"cursor": None},
        }],
        "api/public/v3/scores": [
            {
                "data": [
                    {"name": "processing_success", "value": 1},
                    {"name": "processing_success", "value": 0},
                ],
                "meta": {"cursor": "next"},
            },
            {
                "data": [{"name": "document_success_rate", "value": 0.75}],
                "meta": {"cursor": None},
            },
        ],
    }
    monkeypatch.setattr("app.services.langfuse_metrics.httpx.Client", _FakeClient)

    result = fetch_langfuse_metrics(_settings(), datetime(2026, 9, 1, tzinfo=timezone.utc))

    assert result.available is True
    assert result.trace_count == 4
    assert result.observation_count == 4
    assert result.score_count == 3
    assert result.total_cost_usd == 0.0051
    assert result.cost_by_model[0].model == "gpt-4o-mini"
    assert result.cost_by_model[0].observations == 2
    assert result.scores[0].name == "processing_success"
    assert result.scores[0].average == 0.5


def test_langfuse_metrics_are_optional_and_fail_safe(monkeypatch):
    assert fetch_langfuse_metrics(Settings(langfuse_enabled=False), None).available is False

    class _FailingClient(_FakeClient):
        def get(self, path, params=None):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr("app.services.langfuse_metrics.httpx.Client", _FailingClient)
    result = fetch_langfuse_metrics(_settings(), None)
    assert result.available is False
    assert result.error is not None
