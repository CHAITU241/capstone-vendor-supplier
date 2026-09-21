import time

from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings, get_settings
from app.schemas import (
    GeneralAssistantRequest,
    GeneralAssistantResponse,
    GeneralAssistantRun,
)
from app.services.openai_service import AIConfigurationError, get_openai_service
from app.services.assistant_scope import is_onboarding_question
from app.services.policy_retrieval import policy_context_for, supplier_facing_answer
from app.services.redaction import redact_pii

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/chat", response_model=GeneralAssistantResponse)
def chat(payload: GeneralAssistantRequest, settings: Settings = Depends(get_settings)) -> GeneralAssistantResponse:
    return answer_chat(payload, settings)


def answer_chat(
    payload: GeneralAssistantRequest,
    settings: Settings,
    application_context: str = "",
) -> GeneralAssistantResponse:
    if payload.messages[-1].role != "user":
        raise HTTPException(status_code=422, detail="The last message must be a user question.")

    total_characters = sum(len(message.content) for message in payload.messages)
    if total_characters > 10000:
        raise HTTPException(status_code=422, detail="The conversation is too long. Start a new chat.")

    question = payload.messages[-1].content
    previous_questions = [message.content for message in payload.messages[:-1] if message.role == "user"]
    if not is_onboarding_question(question, previous_questions):
        return GeneralAssistantResponse(
            answer="I can help with supplier onboarding, required documents, and using this portal. What would you like to know about those?",
            run=GeneralAssistantRun(
                model="scope-check", prompt_version=settings.assistant_prompt_version,
                input_tokens=0, output_tokens=0, latency_ms=0, redaction_counts={},
            ),
        )

    try:
        ai = get_openai_service()
    except AIConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    started = time.perf_counter()
    try:
        sanitized_messages: list[dict[str, str]] = []
        redaction_counts: dict[str, int] = {}
        for message in payload.messages:
            redaction = redact_pii(message.content)
            sanitized_messages.append({"role": message.role, "content": redaction.text})
            for category, count in redaction.counts.items():
                redaction_counts[category] = redaction_counts.get(category, 0) + count
        context = policy_context_for(payload.messages[-1].content)
        if application_context:
            context = f"{application_context}\n\n{context}"
        result = ai.answer_general_question(sanitized_messages, context)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="The supplier assistant could not answer this question.") from exc

    return GeneralAssistantResponse(
        answer=supplier_facing_answer(payload.messages[-1].content, result.value.answer),
        run=GeneralAssistantRun(
            model=settings.active_answer_model,
            prompt_version=settings.assistant_prompt_version,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
            redaction_counts=redaction_counts,
        ),
    )
