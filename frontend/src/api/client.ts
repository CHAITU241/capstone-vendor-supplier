import type {
  ApiErrorBody,
  ComplianceRunResponse,
  DecisionResponse,
  DocumentType,
  GeneralAssistantMessage,
  GeneralAssistantResponse,
  ProcessSupplierResponse,
  SupplierCreate,
  SupplierDetail,
  SupplierDocument,
  SupplierQuestionResponse,
  SupplierSummary,
} from './types'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message)
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, options)
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

export const api = {
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
  processSupplier: (supplierId: string) =>
    request<ProcessSupplierResponse>(`/suppliers/${supplierId}/process`, {
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
