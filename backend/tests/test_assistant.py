import pytest
from fastapi import HTTPException

from app.config import Settings
from app.routers.assistant import answer_chat, chat
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
    assert "India-based incorporated suppliers" in contexts[0]
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


def test_assistant_returns_document_names_when_model_returns_internal_ids(monkeypatch) -> None:
    class FakeAssistant:
        def answer_general_question(self, messages, policy_context="") -> ModelResult[GeneralAssistantAnswer]:
            return ModelResult(
                value=GeneralAssistantAnswer(answer="BASE-001, SEC-001, INS-CYB-001"),
                input_tokens=1,
                output_tokens=1,
            )

    monkeypatch.setattr("app.routers.assistant.get_openai_service", lambda: FakeAssistant())
    payload = GeneralAssistantRequest(
        messages=[GeneralAssistantMessage(role="user", content="What evidence does a cybersecurity supplier need?")]
    )

    result = chat(payload, Settings())

    assert "Business registration certificate" in result.answer
    assert "Insurer-issued cyber liability insurance certificate" in result.answer
    assert "BASE-001" not in result.answer


def test_assistant_refuses_off_topic_question_without_calling_model(monkeypatch) -> None:
    monkeypatch.setattr("app.routers.assistant.get_openai_service", lambda: pytest.fail("AI should not be called"))
    payload = GeneralAssistantRequest(
        messages=[
            GeneralAssistantMessage(role="user", content="What evidence does a cybersecurity supplier need?"),
            GeneralAssistantMessage(role="assistant", content="Prepare your registration and tax evidence."),
            GeneralAssistantMessage(role="user", content="Who is the president of India?"),
        ]
    )

    result = chat(payload, Settings())

    assert "supplier onboarding" in result.answer
    assert result.run.input_tokens == 0


def test_assistant_accepts_long_prior_answer_in_conversation(monkeypatch) -> None:
    class FakeAssistant:
        def answer_general_question(self, messages, policy_context="") -> ModelResult[GeneralAssistantAnswer]:
            return ModelResult(value=GeneralAssistantAnswer(answer="Use the current certificate."), input_tokens=1, output_tokens=1)

    monkeypatch.setattr("app.routers.assistant.get_openai_service", lambda: FakeAssistant())
    payload = GeneralAssistantRequest(
        messages=[
            GeneralAssistantMessage(role="user", content="What evidence does a cybersecurity supplier need?"),
            GeneralAssistantMessage(role="assistant", content="Details: " + "x" * 2500),
            GeneralAssistantMessage(role="user", content="What about the insurance certificate?"),
        ]
    )

    assert chat(payload, Settings()).answer == "Use the current certificate."


def test_assistant_rejects_an_oversized_conversation(monkeypatch) -> None:
    monkeypatch.setattr("app.routers.assistant.get_openai_service", lambda: pytest.fail("AI should not be called"))
    payload = GeneralAssistantRequest(
        messages=[GeneralAssistantMessage(role="user", content="x" * 2000)] * 6
    )

    with pytest.raises(HTTPException, match="conversation is too long"):
        chat(payload, Settings())


def test_signed_in_application_context_is_passed_to_assistant(monkeypatch) -> None:
    contexts: list[str] = []

    class FakeAssistant:
        def answer_general_question(self, messages, policy_context="") -> ModelResult[GeneralAssistantAnswer]:
            contexts.append(policy_context)
            return ModelResult(
                value=GeneralAssistantAnswer(answer="Your human review is still in progress."),
                input_tokens=1,
                output_tokens=1,
            )

    monkeypatch.setattr("app.routers.assistant.get_openai_service", lambda: FakeAssistant())
    payload = GeneralAssistantRequest(
        messages=[GeneralAssistantMessage(role="user", content="Is my review complete?")]
    )

    result = answer_chat(
        payload,
        Settings(),
        "CURRENT SIGNED-IN APPLICATION (authoritative account context):\n"
        "Selected service: Technology and Digital Services / Cybersecurity.\n"
        "Journey status: Human reviewer verification is still in progress.",
    )

    assert result.answer == "Your human review is still in progress."
    assert "Cybersecurity" in contexts[0]
    assert "still in progress" in contexts[0]
