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
    erp_payload: dict | None = None
    document_count: int = 0


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    supplier_id: uuid.UUID
    document_type: DocumentType
    filename: str
    content_type: str
    file_size: int
    sha256: str | None = None
    revision: int = 1
    page_count: int
    processing_status: ProcessingStatus
    error_message: str | None
    ai_extraction_status: Literal["pending", "processing", "ready", "failed"] = "pending"
    ai_extraction_error: str | None = None
    ai_index_status: Literal["pending", "processing", "ready", "failed"] = "pending"
    ai_index_error: str | None = None
    review_status: str = "pending"
    review_comment: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class DocumentRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    supplier_id: uuid.UUID
    document_type: str
    revision: int
    filename: str
    content_type: str
    file_size: int
    sha256: str
    uploaded_at: datetime
    archived_at: datetime


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
    review_status: str = "pending"
    review_comment: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
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
    tax_reference: str | None
    bank_account_number: str | None
    bank_ifsc: str | None
    requirements: Checklist
    documents: list[DocumentRead]
    audit_events: list[AuditEventRead]
    extracted_fields: list[ExtractedFieldRead]
    ai_runs: list[AiRunRead]
    compliance_results: list[ComplianceResultRead]
    erp_preview: dict


class ExtractedFieldUpdate(BaseModel):
    value: str = Field(min_length=1, max_length=1000)
    page_number: int = Field(ge=1)
    reviewer_name: str = Field(default="Demo reviewer", min_length=2, max_length=100)


class ReviewSelectionRequest(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    action: Literal["verify", "dispute"]
    reason: str | None = Field(default=None, max_length=1000)
    reviewer_name: str = Field(default="Demo reviewer", min_length=2, max_length=100)


class EvidenceReviewRequest(BaseModel):
    action: Literal["verify", "dispute"]
    reason: str | None = Field(default=None, max_length=1000)
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


class ErpValidationResponse(BaseModel):
    valid: bool
    errors: list[dict]
    warnings: list[dict]
    existing_erp_supplier_id: str | None = None
    idempotent_replay: bool = False


class ErpRecordRead(BaseModel):
    erp_supplier_id: str
    supplier_reference: str | None = None
    source_supplier_id: uuid.UUID
    legal_name: str
    tax_reference: str
    category: str
    subcategory: str
    status: str
    payload: dict
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProcessSupplierResponse(BaseModel):
    run: AiRunRead
    field_count: int
    chunk_count: int
    redaction_counts: dict[str, int]
    processed_document_count: int = 0
    failed_document_count: int = 0


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
    content: str = Field(min_length=1, max_length=8000)


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
