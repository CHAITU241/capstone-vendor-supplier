import pytest

from app.config import Settings
from app.services import openai_service
from app.services.openai_service import AIConfigurationError, build_openai_service


def test_openrouter_takes_priority_and_uses_openrouter_models(monkeypatch) -> None:
    captured: dict = {}
    fake_client = object()

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return fake_client

    monkeypatch.setattr(openai_service, "OpenAI", fake_openai)
    monkeypatch.setattr(
        openai_service,
        "AzureOpenAI",
        lambda **kwargs: pytest.fail("Azure must not be created when OpenRouter is configured"),
    )
    settings = Settings(
        _env_file=None,
        openrouter_api_key="openrouter-key",
        openrouter_site_url="https://vendorlens.example",
        openai_api_key="azure-key",
        azure_openai_endpoint="https://azure.example",
    )

    service = build_openai_service(settings)

    assert service.client is fake_client
    assert settings.ai_provider == "openrouter"
    assert settings.active_extraction_model == "openai/gpt-4o-mini"
    assert settings.active_answer_model == "openai/gpt-4o-mini"
    assert settings.active_embedding_model == "openai/text-embedding-3-small"
    assert captured["api_key"] == "openrouter-key"
    assert captured["base_url"] == "https://openrouter.ai/api/v1"
    assert captured["default_headers"] == {
        "X-Title": "VendorLens AI",
        "HTTP-Referer": "https://vendorlens.example",
    }
    assert service._structured_output_options() == {
        "extra_body": {"provider": {"require_parameters": True}}
    }


def test_azure_is_used_when_openrouter_key_is_empty(monkeypatch) -> None:
    captured: dict = {}
    fake_client = object()

    def fake_azure(**kwargs):
        captured.update(kwargs)
        return fake_client

    monkeypatch.setattr(openai_service, "AzureOpenAI", fake_azure)
    monkeypatch.setattr(
        openai_service,
        "OpenAI",
        lambda **kwargs: pytest.fail("OpenRouter must not be created without its key"),
    )
    settings = Settings(
        _env_file=None,
        openrouter_api_key="   ",
        openai_api_key="azure-key",
        azure_openai_endpoint="https://azure.example/",
        openai_extraction_model="azure-extraction-deployment",
        openai_answer_model="azure-answer-deployment",
        openai_embedding_model="azure-embedding-deployment",
    )

    service = build_openai_service(settings)

    assert service.client is fake_client
    assert settings.ai_provider == "azure"
    assert settings.active_extraction_model == "azure-extraction-deployment"
    assert settings.active_answer_model == "azure-answer-deployment"
    assert settings.active_embedding_model == "azure-embedding-deployment"
    assert captured["api_key"] == "azure-key"
    assert captured["azure_endpoint"] == "https://azure.example"
    assert service._structured_output_options() == {}


def test_configuration_requires_one_complete_provider() -> None:
    with pytest.raises(AIConfigurationError, match="OPENROUTER_API_KEY"):
        build_openai_service(Settings(_env_file=None))

    with pytest.raises(AIConfigurationError, match="AZURE_OPENAI_ENDPOINT"):
        build_openai_service(
            Settings(_env_file=None, openai_api_key="azure-key")
        )
