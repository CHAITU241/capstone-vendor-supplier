from contextlib import contextmanager

from app.config import Settings
from app.services.tracing import LangfuseTracer, telemetry_subject_id


class FakeObservation:
    def __init__(self):
        self.updates = []
        self.trace_updates = []
        self.scores = []

    def update(self, **kwargs):
        self.updates.append(kwargs)

    def update_trace(self, **kwargs):
        self.trace_updates.append(kwargs)

    def score_trace(self, **kwargs):
        self.scores.append(kwargs)


class FakeContext:
    def __init__(self, observation):
        self.observation = observation

    def __enter__(self):
        return self.observation

    def __exit__(self, *_):
        return False


class FakeClient:
    def __init__(self):
        self.calls = []
        self.observations = []

    def start_as_current_observation(self, **kwargs):
        self.calls.append(kwargs)
        observation = FakeObservation()
        self.observations.append(observation)
        return FakeContext(observation)


def test_langfuse_is_optional_without_credentials() -> None:
    tracer = LangfuseTracer(
        Settings(langfuse_enabled=True, langfuse_public_key=None, langfuse_secret_key=None)
    )

    with tracer.generation(
        name="test.generation",
        model="test-model",
        input_data={"request_chars": 10},
    ) as observation:
        observation.update(output={"answer_chars": 4})

    assert tracer.client is None


def test_tracing_defaults_to_metadata_only() -> None:
    tracer = LangfuseTracer(
        Settings(langfuse_capture_content=False, langfuse_public_key=None, langfuse_secret_key=None)
    )

    assert tracer.input_payload({"request_chars": 10}, "sensitive text") == {
        "request_chars": 10
    }


def test_tracing_content_capture_requires_explicit_opt_in() -> None:
    tracer = LangfuseTracer(
        Settings(langfuse_capture_content=True, langfuse_public_key=None, langfuse_secret_key=None)
    )

    assert tracer.input_payload({"request_chars": 10}, "redacted text") == {
        "metadata": {"request_chars": 10},
        "content": "redacted text",
    }


def test_trace_adds_safe_grouping_and_generation_metadata() -> None:
    tracer = LangfuseTracer(Settings(
        openrouter_api_key="test-key",
        langfuse_enabled=False,
        langfuse_capture_content=False,
    ))
    fake = FakeClient()
    tracer.client = fake
    propagated = []

    @contextmanager
    def fake_propagation(**kwargs):
        propagated.append(kwargs)
        yield

    tracer.propagate_attributes = fake_propagation
    subject = telemetry_subject_id("random-supplier-uuid")

    with tracer.trace(
        name="supplier.document.processing",
        input_data={"document_count": 2},
        metadata={"prompt_version": "extraction-v4"},
        subject_id=subject,
        tags=["processing"],
    ) as trace:
        trace.score_trace(name="processing_success", value=1)
        with tracer.generation(
            name="supplier.document.extraction",
            model="openai/gpt-4o-mini",
            input_data={"text_chars": 120},
            metadata={"document_type": "registration"},
        ):
            pass

    assert fake.calls[0]["as_type"] == "span"
    assert propagated[0]["user_id"] == subject
    assert propagated[0]["tags"] == ["processing"]
    assert fake.observations[0].scores == [{"name": "processing_success", "value": 1}]
    assert fake.calls[1]["model"] == "gpt-4o-mini"
    assert fake.calls[1]["metadata"] == {
        "provider": "openrouter",
        "provider_model": "openai/gpt-4o-mini",
        "document_type": "registration",
    }


def test_telemetry_subject_is_stable_and_does_not_expose_source_id() -> None:
    first = telemetry_subject_id("supplier-secret-id")
    assert first == telemetry_subject_id("supplier-secret-id")
    assert first.startswith("supplier-")
    assert "supplier-secret-id" not in first
