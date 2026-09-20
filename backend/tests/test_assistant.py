import pytest
from fastapi import HTTPException

from app.config import Settings
from app.routers.assistant import chat
from app.schemas import GeneralAssistantMessage, GeneralAssistantRequest
from app.services.openai_service import GeneralAssistantAnswer, ModelResult


def test_assistant_requires_a_user_message_at_the_end() -> None:
    payload = GeneralAssistantRequest(
        messages=[GeneralAssistantMessage(role="assistant", content="Welcome.")]
    )

    with pytest.raises(HTTPException, match="last message"):
        chat(payload, Settings())


def test_assistant_passes_only_conversation_messages_to_ai(monkeypatch) -> None:
    captured: list[dict[str, str]] = []
    contexts: list[str] = []

    class FakeAssistant:
        def answer_general_question(self, messages: list[dict[str, str]], policy_context: str = "") -> ModelResult[GeneralAssistantAnswer]:
            captured.extend(messages)
            contexts.append(policy_context)
            return ModelResult(
                value=GeneralAssistantAnswer(answer="Prepare the documents requested by the buyer."),
                input_tokens=11,
                output_tokens=7,
            )

    monkeypatch.setattr("app.routers.assistant.get_openai_service", lambda: FakeAssistant())
    payload = GeneralAssistantRequest(
        messages=[
            GeneralAssistantMessage(role="user", content="What should I prepare?"),
            GeneralAssistantMessage(role="assistant", content="Start with your registration records."),
            GeneralAssistantMessage(role="user", content="Anything else?"),
        ]
    )

    result = chat(payload, Settings(openai_answer_model="gpt-test"))

    assert result.answer.startswith("Prepare the documents")
    assert captured == [message.model_dump() for message in payload.messages]
    assert "Synthetic buyer policy v1.1" in contexts[0]
    assert result.run.model == "gpt-test"
    assert result.run.input_tokens == 11
    assert result.run.output_tokens == 7
    assert result.run.redaction_counts == {}


def test_assistant_redacts_pii_before_ai(monkeypatch) -> None:
    captured: list[dict[str, str]] = []

    class FakeAssistant:
        def answer_general_question(self, messages: list[dict[str, str]], policy_context: str = "") -> ModelResult[GeneralAssistantAnswer]:
            captured.extend(messages)
            return ModelResult(
                value=GeneralAssistantAnswer(answer="Use the portal's secure upload flow."),
                input_tokens=1,
                output_tokens=1,
            )

    monkeypatch.setattr("app.routers.assistant.get_openai_service", lambda: FakeAssistant())
    payload = GeneralAssistantRequest(
        messages=[GeneralAssistantMessage(role="user", content="Email me at supplier@example.com")]
    )

    result = chat(payload, Settings())

    assert "supplier@example.com" not in captured[0]["content"]
    assert captured[0]["content"] == "Email me at [EMAIL_1]"
    assert result.run.redaction_counts == {"EMAIL": 1}


def test_assistant_rejects_an_oversized_conversation(monkeypatch) -> None:
    monkeypatch.setattr("app.routers.assistant.get_openai_service", lambda: pytest.fail("AI should not be called"))
    payload = GeneralAssistantRequest(
        messages=[GeneralAssistantMessage(role="user", content="x" * 2000)] * 6
    )

    with pytest.raises(HTTPException, match="conversation is too long"):
        chat(payload, Settings())
