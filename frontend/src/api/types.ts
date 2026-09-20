export type SupplierStatus = 'new' | 'processing' | 'needs_review' | 'approved' | 'rejected'
export type DocumentType = 'registration' | 'tax' | 'insurance'
export type ProcessingStatus = 'processing' | 'ready' | 'failed'
export type AiRunType = 'processing' | 'question'
export type AiRunStatus = 'processing' | 'succeeded' | 'failed'
export type ComplianceStatus = 'pass' | 'fail' | 'needs_review'

export interface DocumentChecklist {
  version: string
  status: string
  reason: string
  documents: Array<{ document_type: DocumentType; label: string; why: string }>
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
  document_count: number
}

export interface PortalSession {
  token: string
  role: 'supplier' | 'reviewer'
  email: string | null
}

export interface SupplierApplication {
  id: string
  category: string | null
  subcategory: string | null
  name: string
  country: string | null
  contact_email: string | null
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
  page_count: number
  processing_status: ProcessingStatus
  error_message: string | null
  created_at: string
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
  requirements: DocumentChecklist
  documents: SupplierDocument[]
  audit_events: AuditEvent[]
  extracted_fields: ExtractedField[]
  ai_runs: AiRun[]
  compliance_results: ComplianceResult[]
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

export interface ProcessSupplierResponse {
  run: AiRun
  field_count: number
  chunk_count: number
  redaction_counts: Record<string, number>
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
  run: {
    model: string
    prompt_version: string
    input_tokens: number
    output_tokens: number
    latency_ms: number
    redaction_counts: Record<string, number>
  }
}

export interface ApiErrorBody {
  code: string
  message: string
  detail?: string
  details?: Array<Record<string, unknown>>
}
