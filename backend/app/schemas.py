import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import (
    AiRunStatus,
    AiRunType,
    ComplianceStatus,
    DocumentType,
    ProcessingStatus,
    SupplierStatus,
)
from app.services.document_policy import Checklist


class SupplierCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    country: str = Field(min_length=2, max_length=100)
    contact_email: EmailStr | None = None


class SupplierSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    country: str | None
    contact_email: EmailStr | None
    category: str | None
    subcategory: str | None
    submitted_at: datetime | None
    status: SupplierStatus
    created_at: datetime
    updated_at: datetime
    decision_reason: str | None
    decided_at: datetime | None
    erp_supplier_id: str | None
    document_count: int = 0


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    supplier_id: uuid.UUID
    document_type: DocumentType
    filename: str
    content_type: str
    file_size: int
    page_count: int
    processing_status: ProcessingStatus
    error_message: str | None
    created_at: datetime


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: str
    entity_type: str
    entity_id: str | None
    details: dict
    created_at: datetime


class ExtractedFieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    field_name: str
    value: str
    page_number: int
    confidence: float
    needs_review: bool
    created_at: datetime


class AiRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_type: AiRunType
    status: AiRunStatus
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    retrieval_count: int
    error_message: str | None
    details: dict
    created_at: datetime


class ComplianceResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_code: str
    status: ComplianceStatus
    message: str
    evidence: dict
    checked_at: datetime


class SupplierDetail(SupplierSummary):
    requirements: Checklist
    documents: list[DocumentRead]
    audit_events: list[AuditEventRead]
    extracted_fields: list[ExtractedFieldRead]
    ai_runs: list[AiRunRead]
    compliance_results: list[ComplianceResultRead]


class ExtractedFieldUpdate(BaseModel):
    value: str = Field(min_length=1, max_length=1000)
    page_number: int = Field(ge=1)
    reviewer_name: str = Field(default="Demo reviewer", min_length=2, max_length=100)


class ComplianceRunResponse(BaseModel):
    results: list[ComplianceResultRead]
    approval_ready: bool


class ApprovalRequest(BaseModel):
    confirmed: Literal[True]
    reviewer_name: str = Field(default="Demo reviewer", min_length=2, max_length=100)


class RejectionRequest(BaseModel):
    confirmed: Literal[True]
    reason: str = Field(min_length=10, max_length=1000)
    reviewer_name: str = Field(default="Demo reviewer", min_length=2, max_length=100)


class DecisionResponse(BaseModel):
    supplier_id: uuid.UUID
    status: SupplierStatus
    message: str
    erp_supplier_id: str | None
    decided_at: datetime


class ProcessSupplierResponse(BaseModel):
    run: AiRunRead
    field_count: int
    chunk_count: int
    redaction_counts: dict[str, int]


class SupplierQuestionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class QuestionCitation(BaseModel):
    chunk_id: str
    filename: str
    page_number: int
    excerpt: str


class SupplierQuestionResponse(BaseModel):
    answer: str
    information_found: bool
    citations: list[QuestionCitation]
    run: AiRunRead


class GeneralAssistantMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class GeneralAssistantRequest(BaseModel):
    messages: list[GeneralAssistantMessage] = Field(min_length=1, max_length=12)


class GeneralAssistantRun(BaseModel):
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    redaction_counts: dict[str, int]


class GeneralAssistantResponse(BaseModel):
    answer: str
    run: GeneralAssistantRun


class HealthResponse(BaseModel):
    status: str
    database: str
    chroma: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict] | None = None
