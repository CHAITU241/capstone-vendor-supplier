from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Generic, TypeVar

from openai import AzureOpenAI, OpenAI
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.metrics import observe_ai_call
from app.models import DocumentType
from app.services.tracing import get_langfuse_tracer


class AIConfigurationError(RuntimeError):
    pass


class AIResponseError(RuntimeError):
    pass


class FieldName(str, Enum):
    SUPPLIER_NAME = "supplier_name"
    ADDRESS = "address"
    COUNTRY = "country"
    TAX_IDENTIFIER = "tax_identifier"
    CONTACT_NAME = "contact_name"
    CONTACT_EMAIL = "contact_email"
    INSURANCE_PROVIDER = "insurance_provider"
    INSURANCE_EXPIRY_DATE = "insurance_expiry_date"
    PAYMENT_TERMS = "payment_terms"


class ExtractedValue(BaseModel):
    field_name: FieldName
    value: str | None
    page_number: int | None = Field(default=None, ge=1)
    confidence: float = Field(ge=0, le=1)


class DocumentExtraction(BaseModel):
    classified_document_type: DocumentType
    fields: list[ExtractedValue]


class GroundedAnswer(BaseModel):
    answer: str
    information_found: bool
    cited_chunk_ids: list[str]


class GeneralAssistantAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)


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
        prompt = _read_prompt("extraction_v3.txt")
        input_metadata = {
            "document_type": expected_type.value,
            "filename": filename,
            "text_chars": len(redacted_text),
        }
        with observe_ai_call(
            "supplier.document.extraction", self.settings.active_extraction_model
        ) as ai_metrics:
            with self.tracer.generation(
                name="supplier.document.extraction",
                model=self.settings.active_extraction_model,
                input_data=self.tracer.input_payload(input_metadata, redacted_text),
            ) as generation:
                response = self.client.beta.chat.completions.parse(
                    model=self.settings.active_extraction_model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": (
                                f"Expected upload category: {expected_type.value}\n"
                                f"Filename: {filename}\n\n{redacted_text}"
                            ),
                        },
                    ],
                    response_format=DocumentExtraction,
                    temperature=0,
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
                        "field_names": [field.field_name.value for field in parsed.fields],
                        "field_count": len(parsed.fields),
                    },
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

    def answer_general_question(
        self,
        messages: list[dict[str, str]],
    ) -> ModelResult[GeneralAssistantAnswer]:
        prompt = _read_prompt("supplier_assistant_v2.txt")
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
