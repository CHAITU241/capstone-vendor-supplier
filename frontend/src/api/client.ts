import type {
  AccessConfig,
  ApiErrorBody,
  AdminObservability,
  AdminProfile,
  AssistantHistoryMessage,
  ComplianceRunResponse,
  DecisionResponse,
  DocumentType,
  DocumentRevision,
  ErpRecord,
  ErpValidation,
  GeneralAssistantMessage,
  GeneralAssistantResponse,
  ProcessSupplierResponse,
  PortalSession,
  PolicyCatalog,
  SupplierApplication,
  SupplierCreate,
  SupplierDetail,
  SupplierDocument,
  SupplierQuestionResponse,
  SupplierSummary,
} from './types'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

type PortalRole = PortalSession['role']
const storageKey = (role: PortalRole) => `vendorlens.session.${role}`

function roleForApiPath(path: string): PortalRole | undefined {
  if (path.startsWith('/admin')) return 'admin'
  if (path.startsWith('/suppliers') || path.startsWith('/mock-erp')) return 'reviewer'
  if (path.startsWith('/portal/application')) return 'supplier'
  return undefined
}

function savedToken(role?: PortalRole): string {
  if (!role) return ''
  const saved = localStorage.getItem(storageKey(role))
  try { return saved ? (JSON.parse(saved) as PortalSession).token : '' } catch { return '' }
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message)
  }
}

async function request<T>(path: string, options?: RequestInit, authRole?: PortalRole): Promise<T> {
  const token = savedToken(authRole ?? roleForApiPath(path))
  const headers = new Headers(options?.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${API_URL}${path}`, { ...options, headers })
  if (!response.ok) {
    let message = 'The request could not be completed.'
    try {
      const body = (await response.json()) as ApiErrorBody
      message = body.message ?? body.detail ?? message
    } catch {
      // Keep the fallback message for non-JSON server errors.
    }
    throw new ApiError(message, response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

async function originalFile(path: string): Promise<Blob> {
  const token = savedToken(roleForApiPath(path))
  const response = await fetch(`${API_URL}${path}`, { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' })
  if (!response.ok) {
    let message = 'The original document could not be opened.'
    try { message = ((await response.json()) as ApiErrorBody).message ?? message } catch { /* Keep fallback. */ }
    throw new ApiError(message, response.status)
  }
  return response.blob()
}

export const api = {
  accessConfig: () => request<AccessConfig>('/portal/auth/config'),
  register: (email: string, password: string) => request<PortalSession>('/portal/auth/register', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }),
  }),
  login: (email: string, password: string) => request<PortalSession>('/portal/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }),
  }),
  reviewerDemo: () => request<PortalSession>('/portal/auth/reviewer-demo', { method: 'POST' }),
  reviewerLogin: (email: string, password: string) => request<PortalSession>('/portal/auth/reviewer', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }),
  }),
  adminDemo: () => request<PortalSession>('/portal/auth/admin-demo', { method: 'POST' }),
  adminLogin: (email: string, password: string) => request<PortalSession>('/portal/auth/admin', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }),
  }),
  adminProfiles: () => request<AdminProfile[]>('/admin/profiles'),
  adminObservability: (days = 30) => request<AdminObservability>(`/admin/observability?days=${days}`),
  adminResetPassword: (id: string) => request<{ password: string }>(`/admin/profiles/${id}/reset-password`, { method: 'POST' }),
  adminDeleteProfile: (id: string) => request<void>(`/admin/profiles/${id}`, { method: 'DELETE' }),
  session: (role: PortalRole) => request<PortalSession>('/portal/auth/session', undefined, role),
  logout: (role: PortalRole) => request<void>('/portal/auth/logout', { method: 'POST' }, role),
  getApplication: () => request<SupplierApplication>('/portal/application'),
  getPolicy: () => request<PolicyCatalog>('/portal/policy'),
  saveApplication: (payload: { category: string; subcategory: string; name?: string; country?: string; contact_email?: string; tax_reference?: string; bank_account_number?: string; bank_ifsc?: string }) =>
    request<SupplierApplication>('/portal/application', {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    }),
  submitApplication: () => request<SupplierApplication>('/portal/application/submit', { method: 'POST' }),
  resubmitApplication: () => request<SupplierApplication>('/portal/application/resubmit', { method: 'POST' }),
  uploadApplicationDocument: (documentType: DocumentType, file: File) => {
    const formData = new FormData()
    formData.append('document_type', documentType)
    formData.append('file', file)
    return request<SupplierDocument>('/portal/application/documents', { method: 'POST', body: formData })
  },
  deleteApplicationDocument: (id: string) => request<void>(`/portal/application/documents/${id}`, { method: 'DELETE' }),
  retryApplicationTextExtraction: (id: string) =>
    request<SupplierDocument>(`/portal/application/documents/${id}/text-extraction/retry`, { method: 'POST' }),
  applicationDocumentHistory: () => request<DocumentRevision[]>('/portal/application/documents/history'),
  applicationOriginal: (id: string) => originalFile(`/portal/application/documents/${id}/content`),
  listSuppliers: () => request<SupplierSummary[]>('/suppliers'),
  getSupplier: (id: string) => request<SupplierDetail>(`/suppliers/${id}`),
  createSupplier: (payload: SupplierCreate) =>
    request<SupplierSummary>('/suppliers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  uploadDocument: (supplierId: string, documentType: DocumentType, file: File) => {
    const formData = new FormData()
    formData.append('document_type', documentType)
    formData.append('file', file)
    return request<SupplierDocument>(`/suppliers/${supplierId}/documents`, {
      method: 'POST',
      body: formData,
    })
  },
  deleteDocument: (supplierId: string, documentId: string) =>
    request<void>(`/suppliers/${supplierId}/documents/${documentId}`, {
      method: 'DELETE',
    }),
  retryReviewerTextExtraction: (supplierId: string, documentId: string) =>
    request<SupplierDocument>(`/suppliers/${supplierId}/documents/${documentId}/text-extraction/retry`, { method: 'POST' }),
  reviewerDocumentHistory: (supplierId: string) => request<DocumentRevision[]>(`/suppliers/${supplierId}/documents/history`),
  reviewerOriginal: (supplierId: string, id: string) => originalFile(`/suppliers/${supplierId}/documents/${id}/content`),
  processSupplier: (supplierId: string, refresh = false) =>
    request<ProcessSupplierResponse>(`/suppliers/${supplierId}/process${refresh ? '?refresh=true' : ''}`, {
      method: 'POST',
    }),
  processSupplierDocument: (supplierId: string, documentId: string) =>
    request<ProcessSupplierResponse>(`/suppliers/${supplierId}/documents/${documentId}/process`, {
      method: 'POST',
    }),
  askSupplierQuestion: (supplierId: string, question: string) =>
    request<SupplierQuestionResponse>(`/suppliers/${supplierId}/questions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    }),
  askGeneralAssistant: (messages: GeneralAssistantMessage[]) =>
    request<GeneralAssistantResponse>('/assistant/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages }),
    }),
  askApplicationAssistant: (messages: GeneralAssistantMessage[]) =>
    request<GeneralAssistantResponse>('/portal/application/assistant', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages }),
    }),
  applicationAssistantHistory: () => request<AssistantHistoryMessage[]>('/portal/application/assistant/history'),
  clearApplicationAssistantHistory: () => request<void>('/portal/application/assistant/history', { method: 'DELETE' }),
  askReviewerAssistant: (supplierId: string, messages: GeneralAssistantMessage[]) =>
    request<GeneralAssistantResponse>(`/suppliers/${supplierId}/assistant`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages }),
    }),
  reviewerAssistantHistory: (supplierId: string) =>
    request<AssistantHistoryMessage[]>(`/suppliers/${supplierId}/assistant/history`),
  clearReviewerAssistantHistory: (supplierId: string) =>
    request<void>(`/suppliers/${supplierId}/assistant/history`, { method: 'DELETE' }),
  runCompliance: (supplierId: string) =>
    request<ComplianceRunResponse>(`/suppliers/${supplierId}/compliance/run`, {
      method: 'POST',
    }),
  updateExtractedField: (
    supplierId: string,
    fieldId: string,
    payload: { value: string; page_number: number; reviewer_name?: string },
  ) =>
    request<SupplierDetail['extracted_fields'][number]>(`/suppliers/${supplierId}/fields/${fieldId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  reviewExtractedFields: (supplierId: string, ids: string[], action: 'verify' | 'dispute', reason?: string) =>
    request<SupplierDetail['extracted_fields']>(`/suppliers/${supplierId}/fields/review`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids, action, reason }),
    }),
  reviewEvidence: (supplierId: string, documentId: string, action: 'verify' | 'dispute', reason?: string) =>
    request<SupplierDocument>(`/suppliers/${supplierId}/documents/${documentId}/review`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, reason }),
    }),
  validateErpRecord: (supplierId: string) =>
    request<ErpValidation>(`/suppliers/${supplierId}/erp/validate`, { method: 'POST' }),
  getErpRecord: (supplierId: string) => request<ErpRecord>(`/suppliers/${supplierId}/erp/record`),
  listErpRecords: () => request<ErpRecord[]>('/mock-erp/records'),
  approveSupplier: (supplierId: string, reviewerName = 'Demo reviewer') =>
    request<DecisionResponse>(`/suppliers/${supplierId}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmed: true, reviewer_name: reviewerName }),
    }),
  rejectSupplier: (supplierId: string, reason: string, reviewerName = 'Demo reviewer') =>
    request<DecisionResponse>(`/suppliers/${supplierId}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmed: true, reason, reviewer_name: reviewerName }),
    }),
}
