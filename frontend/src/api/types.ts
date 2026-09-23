export type SupplierStatus = 'new' | 'processing' | 'needs_review' | 'approved' | 'rejected'
export type DocumentType = string
export type ProcessingStatus = 'processing' | 'ready' | 'failed'
export type AiRunType = 'processing' | 'question'
export type AiRunStatus = 'processing' | 'succeeded' | 'failed'
export type ComplianceStatus = 'pass' | 'fail' | 'needs_review'

export interface DocumentChecklist {
  version: string
  status: string
  reason: string
  documents: Array<{ document_type: DocumentType; requirement_id: string; label: string; why: string; accepted_evidence: string; required_fields: string; checks: string[]; source: string }>
}

export interface PolicyCatalog {
  version: string
  status: string
  scope: string
  baseline: string[]
  requirements: Record<string, { label: string }>
  categories: Array<{ code: string; label: string; subcategories: Array<{ code: string; label: string; definition: string; examples: string; boundary: string; requirements: string[]; source: string }> }>
}

export interface SupplierCreate {
  name: string
  country: string
  contact_email?: string
}

export interface SupplierSummary {
  id: string
  name: string
  country: string | null
  contact_email: string | null
  category: string | null
  subcategory: string | null
  submitted_at: string | null
  status: SupplierStatus
  created_at: string
  updated_at: string
  decision_reason: string | null
  decided_at: string | null
  erp_supplier_id: string | null
  erp_payload: Record<string, unknown> | null
  document_count: number
}

export interface PortalSession {
  token: string
  role: 'supplier' | 'reviewer' | 'admin'
  email: string | null
}

export interface AccessConfig {
  reviewer_auth_enabled: boolean
  admin_auth_enabled: boolean
}

export interface AdminProfile {
  id: string
  name: string
  email: string | null
  status: SupplierStatus
  created_at: string
  submitted_at: string | null
  document_count: number
  archived_count: number
}

export interface AdminMetricGroup {
  label: string
  calls: number
  input_tokens: number
  output_tokens: number
  average_latency_ms: number
  failures: number
}

export interface AdminObservability {
  generated_at: string
  window_days: number
  provider: string
  extraction_model: string
  answer_model: string
  embedding_model: string
  ai_configured: boolean
  langfuse_enabled: boolean
  langfuse_configured: boolean
  langfuse_content_capture: boolean
  langfuse_dashboard_url: string | null
  total_runs: number
  successful_runs: number
  failed_runs: number
  in_progress_runs: number
  success_rate: number
  input_tokens: number
  output_tokens: number
  average_latency_ms: number
  p95_latency_ms: number
  question_runs: number
  grounded_answers: number
  guarded_not_found_answers: number
  average_retrieval_count: number
  documents: number
  native_documents: number
  ocr_assisted_documents: number
  failed_text_extractions: number
  ocr_pages: number
  erp_attempts: number
  erp_failures: number
  erp_average_latency_ms: number
  by_model: AdminMetricGroup[]
  by_operation: AdminMetricGroup[]
  by_prompt_version: AdminMetricGroup[]
  recent_runs: Array<{
    id: string
    supplier_reference: string
    run_type: string
    status: string
    model: string
    prompt_version: string
    input_tokens: number
    output_tokens: number
    latency_ms: number
    retrieval_count: number
    created_at: string
  }>
}

export interface SupplierApplication {
  id: string
  category: string | null
  subcategory: string | null
  name: string
  country: string | null
  contact_email: string | null
  tax_reference: string | null
  bank_account_number: string | null
  bank_ifsc: string | null
  submitted_at: string | null
  status: SupplierStatus
  documents: SupplierDocument[]
  requirements: DocumentChecklist
}

export interface SupplierDocument {
  id: string
  supplier_id: string
  document_type: DocumentType
  filename: string
  content_type: string
  file_size: number
  sha256: string | null
  revision: number
  page_count: number
  processing_status: ProcessingStatus
  error_message: string | null
  text_extraction_method: 'native' | 'ocr' | 'mixed' | null
  ocr_pages: number[]
  ocr_language: string | null
  ocr_warnings: string[]
  ai_extraction_status: 'pending' | 'processing' | 'ready' | 'failed'
  ai_extraction_error: string | null
  ai_index_status: 'pending' | 'processing' | 'ready' | 'failed'
  ai_index_error: string | null
  review_status: 'pending' | 'attention' | 'verified' | 'disputed'
  review_comment: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  created_at: string
}

export interface DocumentRevision {
  id: string
  supplier_id: string
  document_type: string
  revision: number
  filename: string
  content_type: string
  file_size: number
  sha256: string
  uploaded_at: string
  archived_at: string
}

export interface AuditEvent {
  id: string
  action: string
  entity_type: string
  entity_id: string | null
  details: Record<string, unknown>
  created_at: string
}

export interface ExtractedField {
  id: string
  document_id: string
  field_name: string
  value: string
  page_number: number
  confidence: number
  needs_review: boolean
  review_status: 'pending' | 'attention' | 'verified' | 'corrected' | 'disputed'
  review_comment: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  created_at: string
}

export interface AiRun {
  id: string
  run_type: AiRunType
  status: AiRunStatus
  model: string
  prompt_version: string
  input_tokens: number
  output_tokens: number
  latency_ms: number
  retrieval_count: number
  error_message: string | null
  details: Record<string, unknown>
  created_at: string
}

export interface ComplianceResult {
  id: string
  rule_code: string
  status: ComplianceStatus
  message: string
  evidence: Record<string, unknown>
  checked_at: string
}

export interface SupplierDetail extends SupplierSummary {
  tax_reference: string | null
  bank_account_number: string | null
  bank_ifsc: string | null
  requirements: DocumentChecklist
  documents: SupplierDocument[]
  audit_events: AuditEvent[]
  extracted_fields: ExtractedField[]
  ai_runs: AiRun[]
  compliance_results: ComplianceResult[]
  erp_preview: {
    payload: Record<string, unknown>
    sources: Record<string, {
      source: 'system_generated' | 'supplier_entered' | 'reviewed_evidence' | 'not_available'
      label: string
      field_id?: string
      document_id?: string
      review_status?: string
    }>
  }
}

export interface ComplianceRunResponse {
  results: ComplianceResult[]
  approval_ready: boolean
}

export interface DecisionResponse {
  supplier_id: string
  status: SupplierStatus
  message: string
  erp_supplier_id: string | null
  decided_at: string
}

export interface ErpValidation {
  valid: boolean
  errors: Array<{ field: string; code: string; message: string }>
  warnings: Array<{ field: string; code: string; message: string }>
  existing_erp_supplier_id: string | null
  idempotent_replay: boolean
}

export interface ErpRecord {
  erp_supplier_id: string
  supplier_reference: string | null
  source_supplier_id: string
  legal_name: string
  tax_reference: string
  category: string
  subcategory: string
  status: string
  payload: Record<string, unknown>
  created_at: string | null
  updated_at: string | null
}

export interface ProcessSupplierResponse {
  run: AiRun
  field_count: number
  chunk_count: number
  redaction_counts: Record<string, number>
  processed_document_count: number
  failed_document_count: number
}

export interface QuestionCitation {
  chunk_id: string
  filename: string
  page_number: number
  excerpt: string
}

export interface SupplierQuestionResponse {
  answer: string
  information_found: boolean
  citations: QuestionCitation[]
  run: AiRun
}

export interface GeneralAssistantMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface GeneralAssistantResponse {
  answer: string
  citations: QuestionCitation[]
  run: {
    model: string
    prompt_version: string
    input_tokens: number
    output_tokens: number
    latency_ms: number
    redaction_counts: Record<string, number>
  }
}

export interface AssistantHistoryMessage extends GeneralAssistantMessage {
  id: string
  citations: QuestionCitation[]
  created_at: string
}

export interface ApiErrorBody {
  code: string
  message: string
  detail?: string
  details?: Array<Record<string, unknown>>
}
