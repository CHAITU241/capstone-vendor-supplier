from app.config import Settings
from app.services.tracing import LangfuseTracer


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
