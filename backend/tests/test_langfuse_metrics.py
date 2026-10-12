from datetime import datetime, timezone
from types import SimpleNamespace

from app.config import Settings
from app.services.langfuse_metrics import fetch_langfuse_metrics


def _settings() -> Settings:
    return Settings(
        langfuse_enabled=True,
        langfuse_public_key="pk-test",
        langfuse_secret_key="sk-test",
        langfuse_base_url="https://example.test",
    )


class _ObservationApi:
    def get_many(self, **_):
        return SimpleNamespace(
            data=[
                SimpleNamespace(trace_id="trace-a", provided_model_name="gpt-4o-mini", metadata={}, total_cost=0.003),
                SimpleNamespace(trace_id="trace-a", provided_model_name="gpt-4o-mini", metadata={}, total_cost=0.002),
                SimpleNamespace(trace_id="trace-b", provided_model_name=None, metadata={"provider_model": "openai/text-embedding-3-small"}, total_cost=0.0001),
                SimpleNamespace(trace_id="trace-c", provided_model_name=None, metadata={}, total_cost=None),
                SimpleNamespace(trace_id="trace-c", provided_model_name=None, metadata={}, total_cost=0.0002),
            ],
            meta=SimpleNamespace(cursor=None),
        )


class _ScoreApi:
    def __init__(self):
        self.page = 0

    def get_many_v3(self, **_):
        self.page += 1
        if self.page == 1:
            return SimpleNamespace(
                data=[
                    SimpleNamespace(name="processing_success", value=1),
                    SimpleNamespace(name="processing_success", value=0),
                ],
                meta=SimpleNamespace(cursor="next"),
            )
        return SimpleNamespace(
            data=[SimpleNamespace(name="document_success_rate", value=0.75)],
            meta=SimpleNamespace(cursor=None),
        )


def _api():
    return SimpleNamespace(observations=_ObservationApi(), scores_v3=_ScoreApi())


def test_langfuse_metrics_group_cost_and_scores():
    result = fetch_langfuse_metrics(
        _settings(), datetime(2026, 9, 1, tzinfo=timezone.utc), api=_api()
    )

    assert result.available is True
    assert result.trace_available is True
    assert result.usage_available is True
    assert result.scores_available is True
    assert result.trace_count == 3
    assert result.observation_count == 5
    assert result.score_count == 3
    assert result.total_cost_usd == 0.0053
    assert result.cost_by_model[0].model == "gpt-4o-mini"
    assert result.cost_by_model[0].observations == 2
    assert result.cost_by_model[1].model == "Unattributed"
    assert result.cost_by_model[2].model == "text-embedding-3-small"
    assert result.scores[0].name == "processing_success"
    assert result.scores[0].average == 0.5


def test_langfuse_metric_failures_are_isolated():
    class _FailingObservationApi:
        def get_many(self, **_):
            raise RuntimeError("observation endpoint unavailable")

    api = _api()
    api.observations = _FailingObservationApi()
    result = fetch_langfuse_metrics(_settings(), None, api=api)

    assert result.available is True
    assert result.trace_available is False
    assert result.usage_available is False
    assert result.scores_available is True
    assert result.trace_count == 0
    assert result.observation_count == 0
    assert result.error is not None
    assert "cost, traces and observations" in result.error


def test_langfuse_metrics_are_optional_and_fail_safe():
    assert fetch_langfuse_metrics(Settings(langfuse_enabled=False), None).available is False

    class _FailingApi:
        def __getattr__(self, _):
            raise RuntimeError("offline")

    result = fetch_langfuse_metrics(_settings(), None, api=_FailingApi())
    assert result.available is False
    assert result.error is not None
