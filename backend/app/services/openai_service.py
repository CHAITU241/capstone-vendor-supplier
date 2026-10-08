from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import time
from typing import Generic, Literal, TypeVar

from openai import AzureOpenAI, OpenAI, LengthFinishReasonError
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.metrics import observe_ai_call
from app.models import DocumentType
from app.services.document_policy import (
    evidence_slot_for_document_type,
    extraction_field_names,
    load_policy,
    requirement_id_for_document_type,
)
from app.services.tracing import get_langfuse_tracer


class AIConfigurationError(RuntimeError):
    pass


class AIResponseError(RuntimeError):
    pass


class ExtractedValue(BaseModel):
    field_name: str = Field(min_length=1, max_length=100)
    value: str | None = Field(
        default=None,
        max_length=300,
        description="A concise scalar copied from the document; never a paragraph or explanation.",
    )
    page_number: int | None = Field(default=None, ge=1)
    confidence: float = Field(ge=0, le=1)


class PolicyCheckAssessment(BaseModel):
    check_number: int = Field(ge=1, le=2)
    result: Literal["matched", "not_matched", "human_review"]
    reason: str = Field(min_length=1, max_length=300)
    evidence_fields: list[str] = Field(default_factory=list, max_length=12)
    page_number: int | None = Field(default=None, ge=1)


class DocumentExtraction(BaseModel):
    classified_document_type: DocumentType
    fields: list[ExtractedValue] = Field(max_length=12)
    policy_checks: list[PolicyCheckAssessment] = Field(min_length=2, max_length=2)


class AdditionalEvidenceExtraction(BaseModel):
    fields: list[ExtractedValue] = Field(default_factory=list, max_length=12)


class GroundedAnswer(BaseModel):
    answer: str
    information_found: bool
    cited_chunk_ids: list[str]


class GeneralAssistantAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)


class ReviewerAssistantAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)
    cited_chunk_ids: list[str] = Field(default_factory=list, max_length=8)


class ReviewerFlagReason(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)


T = TypeVar("T")


@dataclass(frozen=True)
class ModelResult(Generic[T]):
    value: T
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class EmbeddingResult:
    embeddings: list[list[float]]
    input_tokens: int


@dataclass(frozen=True)
class MetricJudgeResult:
    value: BaseModel
    input_tokens: int
    output_tokens: int
    attempts: list[dict]
    stage_provenance: dict


class MetricJudgeFailure(ValueError):
    """Retain rejected outputs and observed usage when bounded retries exhaust."""
    def __init__(self, reason: str, attempts: list[dict], stage_provenance: dict):
        super().__init__(reason)
        self.attempts = attempts
        self.stage_provenance = stage_provenance

    def assessment(self) -> dict:
        return {"status": "error", "reason": str(self), "attempts": self.attempts,
                "stage_provenance": self.stage_provenance,
                "input_tokens": sum(a["input_tokens"] for a in self.attempts),
                "output_tokens": sum(a["output_tokens"] for a in self.attempts),
                "latency_ms": sum(a["latency_ms"] for a in self.attempts)}


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _read_prompt(filename: str) -> str:
    return (PROMPT_DIR / filename).read_text(encoding="utf-8").strip()


class OpenAIService:
    def __init__(self, client: OpenAI, settings: Settings):
        self.client = client
        self.settings = settings
        self.tracer = get_langfuse_tracer()

    def extract_document(
        self,
        expected_type: DocumentType,
        filename: str,
        redacted_text: str,
    ) -> ModelResult[DocumentExtraction]:
        prompt = _read_prompt("extraction_v4.txt")
        requirement_id = requirement_id_for_document_type(expected_type)
        slot = evidence_slot_for_document_type(expected_type)
        definition = load_policy().requirements.get(requirement_id)
        allowed_fields = extraction_field_names(expected_type)
        if definition:
            slot_label, slot_evidence, slot_fields = slot or (
                definition.label,
                definition.accepted_evidence,
                definition.required_fields,
            )
            prompt += (f"\nExpected upload slot: {expected_type.value}."
                       f" Slot label: {slot_label}."
                       f" Expected policy item: {requirement_id} ({definition.label})."
                       f" Accepted evidence for this upload slot: {slot_evidence}"
                       f" Required fields for this upload slot: {slot_fields}"
                       f" Policy check 1: {definition.checks[0]}"
                       f" Policy check 2: {definition.checks[1]}"
                       f" Return only these exact field_name keys: {', '.join(allowed_fields)}."
                       " Return every listed key exactly once and do not add other keys."
                       " Return exactly two policy_checks, numbered 1 and 2."
                       " For a policy item split into multiple physical files, classify a file as the"
                       " exact expected upload slot when its content matches this slot's evidence; a"
                       " parent policy ID printed on the document is not a type mismatch."
                       " Classify a check as matched only when the document contains clear evidence"
                       " satisfying it, not_matched only for a clear contradiction or threshold"
                       " failure, and human_review when evidence is missing, ambiguous, subjective,"
                       " low-confidence, or requires visual authenticity/signature verification."
                       " Cite only allow-listed field keys in evidence_fields. These are provisional"
                       " AI findings for a reviewer, never an approval decision.")
        input_metadata = {
            "document_type": expected_type.value,
            "file_extension": Path(filename).suffix.lower() or "unknown",
            "text_chars": len(redacted_text),
        }
        with observe_ai_call(
            "supplier.document.extraction", self.settings.active_extraction_model
        ) as ai_metrics:
            with self.tracer.generation(
                name="supplier.document.extraction",
                model=self.settings.active_extraction_model,
                input_data=self.tracer.input_payload(input_metadata, redacted_text),
                metadata={
                    **input_metadata,
                    "prompt_version": self.settings.extraction_prompt_version,
                    "feature": "document_extraction",
                },
            ) as generation:
                response = self.client.beta.chat.completions.parse(
                    model=self.settings.active_extraction_model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": (
                                f"Expected upload category: {expected_type.value}\n"
                                f"File type: {input_metadata['file_extension']}\n\n{redacted_text}"
                            ),
                        },
                    ],
                    response_format=DocumentExtraction,
                    temperature=0,
                    max_completion_tokens=self.settings.extraction_max_completion_tokens,
                    **self._structured_output_options(),
                )
                parsed = response.choices[0].message.parsed
                if parsed is None:
                    raise AIResponseError("The extraction model returned no structured result.")
                usage = response.usage
                result = ModelResult(
                    value=parsed,
                    input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                )
                ai_metrics.input_tokens = result.input_tokens
                ai_metrics.output_tokens = result.output_tokens
                generation.update(
                    output={
                        "classified_document_type": parsed.classified_document_type.value,
                        "field_names": [field.field_name for field in parsed.fields],
                        "field_count": len(parsed.fields),
                    },
                    usage_details={"input": result.input_tokens, "output": result.output_tokens},
                )
                return result

    def extract_additional_evidence(
        self,
        filename: str,
        redacted_text: str,
    ) -> ModelResult[AdditionalEvidenceExtraction]:
        prompt = _read_prompt("additional_evidence_extraction_v1.txt")
        input_metadata = {
            "file_extension": Path(filename).suffix.lower() or "unknown",
            "text_chars": len(redacted_text),
            "feature": "reviewer_additional_evidence_extraction",
        }
        with observe_ai_call(
            "supplier.additional_evidence.extraction", self.settings.active_extraction_model
        ) as ai_metrics:
            with self.tracer.generation(
                name="supplier.additional_evidence.extraction",
                model=self.settings.active_extraction_model,
                input_data=self.tracer.input_payload(input_metadata, redacted_text),
                metadata={**input_metadata, "prompt_version": "additional-evidence-extraction-v1"},
            ) as generation:
                response = self.client.beta.chat.completions.parse(
                    model=self.settings.active_extraction_model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": f"Filename: {filename}\n\n{redacted_text}"},
                    ],
                    response_format=AdditionalEvidenceExtraction,
                    temperature=0,
                    max_completion_tokens=self.settings.extraction_max_completion_tokens,
                    **self._structured_output_options(),
                )
                parsed = response.choices[0].message.parsed
                if parsed is None:
                    raise AIResponseError("The extraction model returned no structured result.")
                usage = response.usage
                result = ModelResult(
                    value=parsed,
                    input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                )
                ai_metrics.input_tokens = result.input_tokens
                ai_metrics.output_tokens = result.output_tokens
                generation.update(
                    output={"field_names": [field.field_name for field in parsed.fields]},
                    usage_details={"input": result.input_tokens, "output": result.output_tokens},
                )
                return result

    def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(embeddings=[], input_tokens=0)
        input_metadata = {"batch_size": len(texts), "text_lengths": [len(text) for text in texts]}
        with observe_ai_call(
            "supplier.document.embeddings", self.settings.active_embedding_model
        ) as ai_metrics:
            with self.tracer.generation(
                name="supplier.document.embeddings",
                model=self.settings.active_embedding_model,
                input_data=self.tracer.input_payload(input_metadata, texts),
                metadata={**input_metadata, "feature": "document_embeddings"},
                observation_type="embedding",
            ) as generation:
                response = self.client.embeddings.create(
                    model=self.settings.active_embedding_model,
                    input=texts,
                )
                usage = response.usage
                result = EmbeddingResult(
                    embeddings=[item.embedding for item in response.data],
                    input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                )
                ai_metrics.input_tokens = result.input_tokens
                generation.update(
                    output={"embedding_count": len(result.embeddings)},
                    usage_details={"input": result.input_tokens},
                )
                return result

    def draft_reviewer_flag_reason(
        self,
        *,
        finding_context: str,
        policy_context: str,
    ) -> ModelResult[ReviewerFlagReason]:
        prompt = _read_prompt("reviewer_flag_reason_v2.txt")
        input_metadata = {
            "finding_chars": len(finding_context),
            "policy_context_chars": len(policy_context),
        }
        content = {"findings": finding_context, "retrieved_policy": policy_context}
        with observe_ai_call(
            "supplier.reviewer.flag_reason", self.settings.active_answer_model
        ) as ai_metrics:
            with self.tracer.generation(
                name="supplier.reviewer.flag_reason",
                model=self.settings.active_answer_model,
                input_data=self.tracer.input_payload(input_metadata, content),
                metadata={
                    **input_metadata,
                    "prompt_version": self.settings.reviewer_flag_prompt_version,
                    "feature": "reviewer_flag_reason",
                    "grounding": "calculated_findings_and_policy_rag",
                },
            ) as generation:
                response = self.client.beta.chat.completions.parse(
                    model=self.settings.active_answer_model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": (
                                f"CALCULATED FINDINGS AND SUPPLIER-FACING RESOLUTION PLAN:\n{finding_context}\n\n"
                                f"RETRIEVED POLICY:\n{policy_context}"
                            ),
                        },
                    ],
                    response_format=ReviewerFlagReason,
                    temperature=0.1,
                    **self._structured_output_options(),
                )
                parsed = response.choices[0].message.parsed
                if parsed is None:
                    raise AIResponseError("The flag-reason model returned no structured result.")
                usage = response.usage
                result = ModelResult(
                    value=parsed,
                    input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                )
                ai_metrics.input_tokens = result.input_tokens
                ai_metrics.output_tokens = result.output_tokens
                generation.update(
                    output={"reason_chars": len(parsed.reason)},
                    usage_details={"input": result.input_tokens, "output": result.output_tokens},
                )
                return result

    def answer_question(
        self,
        redacted_question: str,
        evidence: str,
    ) -> ModelResult[GroundedAnswer]:
        prompt = _read_prompt("rag_answer_v3.txt")
        input_metadata = {
            "question_chars": len(redacted_question),
            "evidence_chars": len(evidence),
        }
        content = {"question": redacted_question, "evidence": evidence}
        with observe_ai_call(
            "supplier.document.question", self.settings.active_answer_model
        ) as ai_metrics:
            with self.tracer.generation(
                name="supplier.document.question",
                model=self.settings.active_answer_model,
                input_data=self.tracer.input_payload(input_metadata, content),
                metadata={
                    **input_metadata,
                    "prompt_version": self.settings.answer_prompt_version,
                    "feature": "document_question",
                },
            ) as generation:
                response = self.client.beta.chat.completions.parse(
                    model=self.settings.active_answer_model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": f"Question:\n{redacted_question}\n\nEvidence:\n{evidence}",
                        },
                    ],
                    response_format=GroundedAnswer,
                    temperature=0,
                    **self._structured_output_options(),
                )
                parsed = response.choices[0].message.parsed
                if parsed is None:
                    raise AIResponseError("The answer model returned no structured result.")
                usage = response.usage
                result = ModelResult(
                    value=parsed,
                    input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                )
                ai_metrics.input_tokens = result.input_tokens
                ai_metrics.output_tokens = result.output_tokens
                generation.update(
                    output={
                        "information_found": parsed.information_found,
                        "citation_intents": len(parsed.cited_chunk_ids),
                        "answer_chars": len(parsed.answer),
                    },
                    usage_details={"input": result.input_tokens, "output": result.output_tokens},
                )
                return result

    def judge_rag_evidence(self, evidence: dict):
        """Isolated relevance and faithfulness calls with strict bounded retries."""
        import json
        import hashlib
        from app.services.rag_evaluation import (
            RELEVANCE_PROMPT, FAITHFULNESS_PROMPT, JUDGE_PROMPT_VERSION,
            relevance_response_schema, faithfulness_response_schema,
            validate_judgment,
        )

        model = self.settings.evaluation_judge_model or self.settings.active_answer_model
        attempts: list[dict] = []
        provenance = {name: {"prompt_version": JUDGE_PROMPT_VERSION + ":" + name,
                             "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
                      for name, prompt in (("relevance", RELEVANCE_PROMPT), ("faithfulness", FAITHFULNESS_PROMPT))}
        # Explicit bounds exclude SDK automatic retries from the attempt count.
        client = self.client.with_options(timeout=60.0, max_retries=0) if hasattr(self.client, "with_options") else self.client

        def assess(stage, prompt, payload, schema, validate):
            messages = [{"role": "system", "content": prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
            for attempt in range(1, 4):
                started = time.perf_counter()
                response = None
                record = {"stage": stage, "attempt": attempt, "input_tokens": 0,
                          "output_tokens": 0, "usage_recorded": False}
                try:
                    response = client.beta.chat.completions.parse(
                        model=model, temperature=0, max_completion_tokens=8192,
                        messages=messages, response_format=schema, **self._structured_output_options(),
                    )
                    message = response.choices[0].message
                    parsed = message.parsed
                    if parsed is None:
                        raise ValueError("No structured judgment was returned.")
                    # Also validates providers/test doubles which bypass SDK parsing.
                    value = schema.model_validate(parsed.model_dump())
                    record["output"] = value.model_dump()
                    result = validate(value)
                    record["status"] = "accepted"
                except (ValueError, LengthFinishReasonError) as exc:
                    record.update(status="rejected", reason=str(exc))
                    response = response or getattr(exc, "completion", None)
                    message = response.choices[0].message if response is not None else None
                    if "output" not in record and message is not None:
                        record["raw_output"] = getattr(message, "content", None)
                    # Feedback requests a new verdict; no missing/invalid label becomes false/true by default.
                    messages.append({"role": "user", "content":
                        "The previous assessment was rejected by validation: " + str(exc) +
                        "\nReturn a complete assessment using the required schema. Copy exact contiguous context quotes; "
                        "do not repair facts or invent support. Required candidate fields/context IDs remain unchanged."})
                except Exception as exc:
                    # Provider/auth/network failures remain visible, with no unbounded retry.
                    record.update(status="error", reason=f"{type(exc).__name__}: metric provider request failed")
                    result = None
                finally:
                    usage = getattr(response, "usage", None)
                    if usage is not None:
                        record.update(input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                                      output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                                      usage_recorded=True)
                    record["latency_ms"] = round((time.perf_counter() - started) * 1000)
                    attempts.append(record)
                if record["status"] == "accepted":
                    return result
                if record["status"] == "error":
                    break
            raise MetricJudgeFailure(f"{stage} judging failed after {record['attempt']} attempt(s): {record['reason']}",
                                     attempts, provenance)

        ranked = evidence["retrieval_top_10"]
        candidate_map = {f"candidate_{i}": c for i, c in enumerate(ranked, 1)}
        # Relevance receives only the question and ranked candidates. No observed/gold answer.
        relevance_payload = {"question": evidence["question"],
                             "candidates": {key: {"filename": c["filename"], "page_number": c["page_number"], "text": c["text"]}
                                            for key, c in candidate_map.items()}}
        def decode_relevance(value):
            return [{"chunk_id": c["chunk_id"], **value.model_dump()[key]} for key, c in candidate_map.items()]

        context_map = {f"context_{i}": c for i, c in enumerate(evidence["generation_context"], 1)}
        # The raw audit is deliberately impossible to see in this separate request.
        faithfulness_payload = {"question": evidence["question"], "answer": evidence["answer"],
                                "information_found": evidence["information_found"],
                                "generation_context": {key: {"filename": c["filename"], "page_number": c["page_number"], "text": c["text"]}
                                                       for key, c in context_map.items()}}
        def decode_claims(value):
            claims = value.model_dump()["claims"]
            for claim in claims:
                for support in claim["support"]:
                    if support["chunk_id"] not in context_map:
                        raise ValueError("Support refers outside actual generation context.")
                    support["chunk_id"] = context_map[support["chunk_id"]]["chunk_id"]
            combined = {"relevance": relevance, "claims": claims}
            return validate_judgment(combined, evidence)

        with observe_ai_call("evaluation.rag.judge", model) as metrics:
            try:
                relevance = assess("relevance", RELEVANCE_PROMPT, relevance_payload,
                                   relevance_response_schema(len(ranked)), decode_relevance) if ranked else []
                judgment = assess("faithfulness", FAITHFULNESS_PROMPT, faithfulness_payload,
                                  faithfulness_response_schema(list(context_map)), decode_claims)
            finally:
                metrics.input_tokens = sum(a["input_tokens"] for a in attempts)
                metrics.output_tokens = sum(a["output_tokens"] for a in attempts)
            return MetricJudgeResult(value=judgment, input_tokens=metrics.input_tokens,
                                     output_tokens=metrics.output_tokens, attempts=attempts,
                                     stage_provenance=provenance)

    def answer_general_question(
        self,
        messages: list[dict[str, str]],
        policy_context: str = "",
    ) -> ModelResult[GeneralAssistantAnswer]:
        prompt = _read_prompt("supplier_assistant_v2.txt") + "\n\nRETRIEVED POLICY EXCERPTS:\n" + policy_context
        input_metadata = {
            "message_count": len(messages),
            "message_lengths": [len(message["content"]) for message in messages],
        }
        with observe_ai_call(
            "supplier.general.assistant", self.settings.active_answer_model
        ) as ai_metrics:
            with self.tracer.generation(
                name="supplier.general.assistant",
                model=self.settings.active_answer_model,
                input_data=self.tracer.input_payload(input_metadata, messages),
                metadata={
                    **input_metadata,
                    "prompt_version": self.settings.assistant_prompt_version,
                    "feature": "supplier_assistant",
                },
            ) as generation:
                response = self.client.beta.chat.completions.parse(
                    model=self.settings.active_answer_model,
                    messages=[{"role": "system", "content": prompt}, *messages],
                    response_format=GeneralAssistantAnswer,
                    temperature=0.2,
                    **self._structured_output_options(),
                )
                parsed = response.choices[0].message.parsed
                if parsed is None:
                    raise AIResponseError("The assistant model returned no structured result.")
                usage = response.usage
                result = ModelResult(
                    value=parsed,
                    input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                )
                ai_metrics.input_tokens = result.input_tokens
                ai_metrics.output_tokens = result.output_tokens
                generation.update(
                    output={"answer_chars": len(parsed.answer)},
                    usage_details={"input": result.input_tokens, "output": result.output_tokens},
                )
                return result

    def answer_reviewer_question(
        self,
        messages: list[dict[str, str]],
        case_context: str,
    ) -> ModelResult[ReviewerAssistantAnswer]:
        prompt = _read_prompt("reviewer_assistant_v1.txt") + "\n\nCASE AND RETRIEVED CONTEXT:\n" + case_context
        input_metadata = {
            "message_count": len(messages),
            "message_lengths": [len(message["content"]) for message in messages],
        }
        with observe_ai_call(
            "supplier.reviewer.assistant", self.settings.active_answer_model
        ) as ai_metrics:
            with self.tracer.generation(
                name="supplier.reviewer.assistant",
                model=self.settings.active_answer_model,
                input_data=self.tracer.input_payload(input_metadata, messages),
                metadata={
                    **input_metadata,
                    "prompt_version": "reviewer-assistant-v1",
                    "feature": "reviewer_assistant",
                },
            ) as generation:
                response = self.client.beta.chat.completions.parse(
                    model=self.settings.active_answer_model,
                    messages=[{"role": "system", "content": prompt}, *messages],
                    response_format=ReviewerAssistantAnswer,
                    temperature=0.2,
                    **self._structured_output_options(),
                )
                parsed = response.choices[0].message.parsed
                if parsed is None:
                    raise AIResponseError("The reviewer assistant model returned no structured result.")
                usage = response.usage
                result = ModelResult(
                    value=parsed,
                    input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                )
                ai_metrics.input_tokens = result.input_tokens
                ai_metrics.output_tokens = result.output_tokens
                generation.update(
                    output={"answer_chars": len(parsed.answer), "citation_intents": len(parsed.cited_chunk_ids)},
                    usage_details={"input": result.input_tokens, "output": result.output_tokens},
                )
                return result

    def _structured_output_options(self) -> dict:
        if self.settings.use_openrouter:
            return {"extra_body": {"provider": {"require_parameters": True}}}
        return {}


def build_openai_service(settings: Settings) -> OpenAIService:
    if settings.use_openrouter:
        assert settings.openrouter_api_key is not None
        default_headers = {"X-Title": settings.openrouter_app_name}
        if settings.openrouter_site_url:
            default_headers["HTTP-Referer"] = settings.openrouter_site_url
        client = OpenAI(
            api_key=settings.openrouter_api_key.get_secret_value().strip(),
            base_url=settings.openrouter_base_url.strip().rstrip("/"),
            default_headers=default_headers,
            timeout=60.0,
            max_retries=2,
        )
        return OpenAIService(client=client, settings=settings)

    if settings.openai_api_key is None or not settings.openai_api_key.get_secret_value().strip():
        raise AIConfigurationError(
            "Configure OPENROUTER_API_KEY or the Azure OPENAI_API_KEY and "
            "AZURE_OPENAI_ENDPOINT in the backend environment."
        )
    if not settings.azure_openai_endpoint or not settings.azure_openai_endpoint.strip():
        raise AIConfigurationError(
            "AZURE_OPENAI_ENDPOINT is required when OPENROUTER_API_KEY is not configured."
        )
    client = AzureOpenAI(
        api_key=settings.openai_api_key.get_secret_value().strip(),
        azure_endpoint=settings.azure_openai_endpoint.strip().rstrip("/"),
        api_version=settings.azure_openai_api_version,
        timeout=60.0,
        max_retries=2,
    )
    return OpenAIService(client=client, settings=settings)


@lru_cache
def get_openai_service() -> OpenAIService:
    return build_openai_service(get_settings())
