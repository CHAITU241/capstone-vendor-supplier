import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded'
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded'
import AttachFileRoundedIcon from '@mui/icons-material/AttachFileRounded'
import BlockRoundedIcon from '@mui/icons-material/BlockRounded'
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded'
import DescriptionRoundedIcon from '@mui/icons-material/DescriptionRounded'
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import DoneAllRoundedIcon from '@mui/icons-material/DoneAllRounded'
import EditRoundedIcon from '@mui/icons-material/EditRounded'
import ExpandLessRoundedIcon from '@mui/icons-material/ExpandLessRounded'
import ExpandMoreRoundedIcon from '@mui/icons-material/ExpandMoreRounded'
import FactCheckRoundedIcon from '@mui/icons-material/FactCheckRounded'
import FlagRoundedIcon from '@mui/icons-material/FlagRounded'
import HowToRegRoundedIcon from '@mui/icons-material/HowToRegRounded'
import {
  Alert, Box, Button, ButtonBase, Card, CardContent, Chip, CircularProgress,
  Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, Divider,
  IconButton, Stack, TextField, Tooltip, Typography,
} from '@mui/material'
import { useCallback, useEffect, useMemo, useState, type ChangeEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { downloadOriginal, openOriginal } from '../api/openOriginal'
import { evidenceDownloadFilename, supplierReference } from '../api/supplierReference'
import type { ComplianceResult, DocumentRevision, ErpRecord, ErpValidation, ExtractedField, ProcessSupplierResponse, SupplierDetail, SupplierDocument } from '../api/types'
import { StatusChip } from '../components/StatusChip'
import { ErpRecordDialog } from '../components/ErpRecordDialog'
import { erpFieldLabels } from '../components/erpRecordLabels'

const fieldLabels: Record<string, string> = {
  supplier_name: 'Supplier name', address: 'Registered address', country: 'Country',
  tax_identifier: 'Tax reference', contact_name: 'Contact name', contact_email: 'Contact email',
  bank_account_number: 'Bank account number', bank_ifsc: 'Bank IFSC',
  insurance_provider: 'Insurance provider', insurance_expiry_date: 'Insurance expiry', payment_terms: 'Payment terms',
}

type RequirementFilter = 'attention' | 'matched' | 'verified' | 'flagged'
type RequirementItem = SupplierDetail['requirements']['documents'][number]

function displayStatus(status: string) { return status.replaceAll('_', ' ') }
function fieldLabel(name: string) { return fieldLabels[name] ?? name.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase()) }
function normalizedFieldKey(name: string) { return name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') }

function comparisonValueMatches(fieldName: string, observed: unknown, expected: unknown) {
  if (observed == null || observed === '' || expected == null || expected === '') return false
  const left = String(observed).trim()
  const right = String(expected).trim()
  if (fieldName === 'bank_account_number') return left === right
  if (['supplier_name', 'tax_identifier', 'bank_ifsc'].includes(fieldName)) {
    const normalize = (value: string) => value.toLocaleLowerCase().replace(/[^a-z0-9]+/g, '')
    return normalize(left) === normalize(right)
  }
  return left.toLocaleLowerCase() === right.toLocaleLowerCase()
}

function ComparedValue({ value, comparison, highlight }: { value: unknown; comparison: unknown; highlight: boolean }) {
  if (value == null || value === '') return <Typography component="span" variant="caption" color="error.dark" fontWeight={700}>Not found</Typography>
  const displayed = String(value)
  const compared = comparison == null ? '' : String(comparison)
  if (!highlight || displayed.length !== compared.length) {
    return <Typography component="span" variant="caption" fontFamily="monospace" fontWeight={highlight ? 700 : 500} sx={{ overflowWrap: 'anywhere' }}>{displayed}</Typography>
  }
  return (
    <Typography component="span" variant="caption" fontFamily="monospace" fontWeight={500} sx={{ overflowWrap: 'anywhere' }}>
      {[...displayed].map((character, index) => (
        <Box
          component="span"
          key={`${character}-${index}`}
          sx={character === compared[index] ? undefined : { bgcolor: 'error.light', color: 'error.contrastText', borderRadius: .5, px: .15, fontWeight: 800 }}
        >
          {character}
        </Box>
      ))}
    </Typography>
  )
}

function policyOutcome(result: ComplianceResult): 'matched' | 'not_matched' | 'human_review' {
  const assessment = String(result.evidence.ai_assessment)
  if (result.status === 'pass' || assessment === 'human_verified' || assessment === 'matched') return 'matched'
  if (result.status === 'fail' || ['not_matched', 'reviewer_flagged'].includes(assessment)) return 'not_matched'
  return 'human_review'
}

function requirementStatus(document: SupplierDocument | undefined, checks: ComplianceResult[]): RequirementFilter {
  if (document?.review_status === 'disputed') return 'flagged'
  if (document?.review_status === 'verified') return 'verified'
  if (document?.review_status === 'attention') return 'attention'
  if (document?.ocr_quality_status === 'review' || document?.ocr_quality_status === 'poor') return 'attention'
  if (!document || document.ai_extraction_status === 'failed' || document.ai_index_status === 'failed') return 'attention'
  if (checks.length === 0) return 'attention'
  if (checks.some((check) => check.evidence.evidence_requires_verification === true)) return 'attention'
  if (checks.some((check) => policyOutcome(check) !== 'matched')) return 'attention'
  return 'matched'
}

function failureReason(message?: string) {
  if (!message) return 'AI processing failed for one or more documents.'
  const index = message.indexOf(' failed. ')
  return index >= 0 ? message.slice(index + 9) : message
}

const erpLabels: Record<string, string> = {
  ...erpFieldLabels,
  supplier_reference: 'Supplier reference', legal_name: 'Legal name', registered_address: 'Registered address',
  country: 'Country', tax_reference: 'Tax reference', contact_name: 'Contact name', contact_email: 'Contact email',
  bank_account_number: 'Bank account', bank_ifsc: 'Bank IFSC', category: 'Category', subcategory: 'Subcategory',
  insurance_provider: 'Insurance provider', insurance_expiry_date: 'Insurance expiry', payment_terms: 'Payment terms',
}

export function SupplierReviewPage() {
  const { supplierId = '' } = useParams()
  const [supplier, setSupplier] = useState<SupplierDetail | null>(null)
  const [history, setHistory] = useState<DocumentRevision[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [fieldToEdit, setFieldToEdit] = useState<ExtractedField | null>(null)
  const [editedValue, setEditedValue] = useState('')
  const [editedPage, setEditedPage] = useState(1)
  const [flagDocumentId, setFlagDocumentId] = useState<string | null>(null)
  const [flagReason, setFlagReason] = useState('')
  const [flagDraftLoading, setFlagDraftLoading] = useState(false)
  const [flagDraftSource, setFlagDraftSource] = useState<'ai_rag' | 'deterministic_fallback' | null>(null)
  const [decisionAction, setDecisionAction] = useState<'approve' | 'reject' | null>(null)
  const [rejectionReason, setRejectionReason] = useState('')
  const [selectedFilter, setSelectedFilter] = useState<RequirementFilter>('attention')
  const [expandedRequirements, setExpandedRequirements] = useState<Set<string>>(new Set())
  const [checkVisibility, setCheckVisibility] = useState<Record<string, boolean>>({})
  const [erpValidation, setErpValidation] = useState<ErpValidation | null>(null)
  const [erpValidationError, setErpValidationError] = useState('')
  const [erpValidating, setErpValidating] = useState(false)
  const [erpRecord, setErpRecord] = useState<ErpRecord | null>(null)
  const [showErpRecord, setShowErpRecord] = useState(false)
  const [confirmAllOpen, setConfirmAllOpen] = useState(false)
  const [otherReviewNote, setOtherReviewNote] = useState('')
  const [additionalVerificationNote, setAdditionalVerificationNote] = useState('')
  const [additionalDocumentToDelete, setAdditionalDocumentToDelete] = useState<string | null>(null)

  const loadSupplier = useCallback(async (options: { includeHistory?: boolean; validateErp?: boolean } = {}) => {
    const { includeHistory = true, validateErp = true } = options
    try {
      const [detail, archived] = await Promise.all([
        api.getSupplier(supplierId),
        includeHistory ? api.reviewerDocumentHistory(supplierId) : Promise.resolve(null),
      ])
      setSupplier(detail)
      if (archived) setHistory(archived)
      if (validateErp) {
        setErpValidating(true)
        try {
          setErpValidation(await api.validateErpRecord(supplierId))
          setErpValidationError('')
        } catch (validationError) {
          setErpValidation(null)
          setErpValidationError(validationError instanceof Error ? validationError.message : 'ERP validation could not be completed.')
        } finally { setErpValidating(false) }
      }
      const policyChecks = detail.compliance_results.filter((result) => result.evidence.kind === 'policy_check')
      const statuses = detail.requirements.documents.map((requirement) => requirementStatus(
        detail.documents.find((document) => document.document_type === requirement.document_type),
        policyChecks.filter((check) => check.evidence.requirement_id === requirement.requirement_id),
      ))
      setSelectedFilter((current) => statuses.includes(current) ? current
        : statuses.includes('attention') ? 'attention'
          : statuses.includes('matched') ? 'matched'
            : statuses.includes('flagged') ? 'flagged' : 'verified')
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Supplier could not be loaded.')
    } finally { setLoading(false) }
  }, [supplierId])

  useEffect(() => { void loadSupplier() }, [loadSupplier])

  useEffect(() => {
    if (supplier?.category === 'OTHER') setOtherReviewNote(supplier.other_review_note ?? '')
  }, [supplier?.category, supplier?.other_review_note])

  const orderedEvidence = useMemo(() => {
    if (!supplier) return []
    const policyChecks = supplier.compliance_results.filter((result) => result.evidence.kind === 'policy_check')
    return supplier.requirements.documents.map((requirement) => {
      const document = supplier.documents.find((item) => item.document_type === requirement.document_type)
      const checks = policyChecks.filter((check) => check.evidence.requirement_id === requirement.requirement_id)
      return {
        requirement, document, checks,
        fields: supplier.extracted_fields.filter((field) => field.document_id === document?.id),
        status: requirementStatus(document, checks),
      }
    })
  }, [supplier])

  const latestProcessingRun = supplier?.ai_runs.find((run) => run.run_type === 'processing')
  const finalized = supplier?.status === 'approved' || supplier?.status === 'rejected'
  const processingActive = supplier?.status === 'processing' || latestProcessingRun?.status === 'processing'
  const complianceReady = Boolean(supplier?.compliance_results.length && supplier.compliance_results.every((result) => result.status === 'pass'))
  const otherReviewReady = supplier?.category !== 'OTHER' || Boolean(supplier.other_review_completed_at)
  const approvalReady = complianceReady && otherReviewReady && Boolean(erpValidation?.valid)

  useEffect(() => {
    if (!processingActive) return
    const timer = window.setInterval(() => {
      void loadSupplier({ includeHistory: false, validateErp: false })
    }, 2_000)
    return () => window.clearInterval(timer)
  }, [loadSupplier, processingActive])

  const findings = useMemo(() => {
    if (!supplier) return []
    const messages: Array<{ severity: 'error' | 'warning' | 'success' | 'info'; text: string }> = []
    if (processingActive && !latestProcessingRun) return [{ severity: 'info' as const, text: 'AI document analysis is starting. This page will update automatically as soon as the run is available.' }]
    if (!latestProcessingRun) return [{ severity: 'info' as const, text: 'AI document analysis has not run yet.' }]
    if (latestProcessingRun.status === 'processing') return [{ severity: 'info' as const, text: 'AI document analysis is running. This page will update automatically when extraction and policy checks finish.' }]
    if (latestProcessingRun.status === 'failed') {
      const total = Number(latestProcessingRun.details.total_documents ?? supplier.documents.length)
      const extracted = Number(latestProcessingRun.details.ready_extractions ?? 0)
      const indexed = Number(latestProcessingRun.details.ready_indexes ?? 0)
      messages.push({
        severity: extracted === 0 && indexed === 0 ? 'error' : 'warning',
        text: extracted === 0 && indexed === 0
          ? `AI processing did not start successfully: 0/${total} documents were extracted or indexed.`
          : `${extracted}/${total} documents were extracted and ${indexed}/${total} were indexed. Successful work was retained.`,
      })
      const failures = Array.isArray(latestProcessingRun.details.failed_documents)
        ? latestProcessingRun.details.failed_documents as Array<{ message?: string }> : []
      const grouped = new Map<string, number>()
      failures.forEach((failure) => grouped.set(failureReason(failure.message), (grouped.get(failureReason(failure.message)) ?? 0) + 1))
      grouped.forEach((count, reason) => messages.push({ severity: 'error', text: `${reason} ${count} document${count === 1 ? '' : 's'} affected.` }))
    }
    const mismatches = Array.isArray(latestProcessingRun.details.classification_mismatches) ? latestProcessingRun.details.classification_mismatches as string[] : []
    const conflicts = Array.isArray(latestProcessingRun.details.field_conflicts) ? latestProcessingRun.details.field_conflicts as string[] : []
    if (mismatches.length) messages.push({ severity: 'warning', text: `${mismatches.length} file(s) may not match the selected evidence type.` })
    if (conflicts.length) messages.push({ severity: 'warning', text: `Conflicting values were detected for: ${conflicts.join(', ')}.` })
    if (!messages.length) messages.push({ severity: 'success', text: 'Document extraction and search indexing completed. Review each requirement below.' })
    return messages
  }, [latestProcessingRun, processingActive, supplier])

  async function viewOriginal(id: string) {
    try { await openOriginal(() => api.reviewerOriginal(supplierId, id)) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not open the original document.') }
  }

  async function downloadFile(document: { id: string; document_type: string; revision: number; filename: string }) {
    const requirement = supplier?.requirements.documents.find((item) => item.document_type === document.document_type)
    const filename = evidenceDownloadFilename({ supplierId, documentType: document.document_type, revision: document.revision, originalFilename: document.filename, requirementId: requirement?.requirement_id, label: requirement?.label ?? document.document_type })
    try { await downloadOriginal(() => api.reviewerOriginal(supplierId, document.id), filename) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not download the original document.') }
  }

  async function viewAdditionalDocument(id: string) {
    try { await openOriginal(() => api.reviewerAdditionalOriginal(supplierId, id)) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not open the additional evidence.') }
  }

  async function uploadAdditionalDocument(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || additionalVerificationNote.trim().length < 10) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api.uploadAdditionalDocument(supplierId, file, additionalVerificationNote.trim())
      setAdditionalVerificationNote('')
      await loadSupplier({ validateErp: false })
      setNotice('Verified email evidence attached to this supplier profile.')
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not attach the additional evidence.')
    } finally { setBusy(false) }
  }

  async function deleteAdditionalDocument() {
    if (!additionalDocumentToDelete) return
    const deleted = await runAction(
      () => api.deleteAdditionalDocument(supplierId, additionalDocumentToDelete),
      'Reviewer-added evidence removed. Record the Policy and Legal outcome again after attaching the correct evidence.',
    )
    if (deleted) {
      setAdditionalDocumentToDelete(null)
      setAdditionalVerificationNote('')
    }
  }

  async function completeOtherReview() {
    if (otherReviewNote.trim().length < 10) return
    if (await runAction(
      () => api.completeOtherReview(supplierId, otherReviewNote.trim()),
      'Policy and Legal review outcome recorded. ERP hand-off can proceed after the remaining checks pass.',
    )) {
      setOtherReviewNote(otherReviewNote.trim())
      setAdditionalVerificationNote('')
    }
  }

  async function runAction(action: () => Promise<unknown>, success: string): Promise<boolean> {
    setBusy(true); setError(''); setNotice('')
    try { await action(); setNotice(success); await loadSupplier(); return true }
    catch (requestError) { await loadSupplier(); setError(requestError instanceof Error ? requestError.message : 'The review action could not be completed.'); return false }
    finally { setBusy(false) }
  }

  async function runProcessing(action: () => Promise<ProcessSupplierResponse>, success: string) {
    setBusy(true); setError(''); setNotice('')
    try {
      const outcome = await action(); await loadSupplier()
      if (outcome.failed_document_count > 0) {
        setError(`AI processing finished with ${outcome.failed_document_count} document${outcome.failed_document_count === 1 ? '' : 's'} still requiring a retry. See document processing for details.`)
        return false
      }
      setNotice(success); return true
    } catch (requestError) { await loadSupplier(); setError(requestError instanceof Error ? requestError.message : 'AI processing could not be completed.'); return false }
    finally { setBusy(false) }
  }

  async function runSupplierAnalysis() {
    const refresh = latestProcessingRun?.status === 'succeeded'
    await runProcessing(() => api.processSupplier(supplierId, refresh), refresh ? 'AI document analysis refreshed successfully.' : 'AI document analysis completed successfully.')
  }

  async function retryDocument(document: SupplierDocument) {
    await runProcessing(() => api.processSupplierDocument(supplierId, document.id), `${document.filename} was extracted and indexed successfully.`)
  }

  async function retryTextExtraction(document: SupplierDocument) {
    setBusy(true); setError(''); setNotice('')
    try {
      const recovered = await api.retryReviewerTextExtraction(supplierId, document.id)
      if (recovered.processing_status === 'failed') throw new Error(recovered.error_message || 'OCR could not read this document.')
      const outcome = await api.processSupplierDocument(supplierId, document.id)
      await loadSupplier()
      if (outcome.failed_document_count) throw new Error('OCR succeeded, but AI extraction or indexing still requires a retry.')
      setNotice(`${document.filename} was recovered with OCR, extracted, and indexed successfully.`)
    } catch (requestError) {
      await loadSupplier()
      setError(requestError instanceof Error ? requestError.message : 'Text extraction could not be retried.')
    } finally { setBusy(false) }
  }

  async function confirmRequirement(document: SupplierDocument, requirement: RequirementItem) {
    await runAction(
      () => api.reviewEvidence(supplierId, document.id, 'verify'),
      `${requirement.label} confirmed. Its document, extracted values, and policy checks were updated together.`,
    )
  }

  async function confirmAllReady() {
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await api.confirmReadyRequirements(supplierId)
      setConfirmAllOpen(false)
      await loadSupplier()
      setNotice(`${result.confirmed_count} ready requirement${result.confirmed_count === 1 ? '' : 's'} confirmed. Each confirmation was recorded in the audit trail.`)
    } catch (requestError) {
      await loadSupplier()
      setError(requestError instanceof Error ? requestError.message : 'The ready requirements could not be confirmed.')
    } finally { setBusy(false) }
  }

  async function submitFlag() {
    if (!flagDocumentId || flagReason.trim().length < 5) return
    if (await runAction(() => api.reviewEvidence(supplierId, flagDocumentId, 'dispute', flagReason.trim()), 'The requirement was flagged and will block approval until resolved.')) {
      setFlagDocumentId(null); setFlagReason(''); setFlagDraftSource(null)
    }
  }

  async function openFlagDialog(documentId: string) {
    setFlagDocumentId(documentId)
    setFlagReason('')
    setFlagDraftSource(null)
    setFlagDraftLoading(true)
    try {
      const draft = await api.draftFlagReason(supplierId, documentId)
      setFlagReason(draft.reason)
      setFlagDraftSource(draft.source)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'A suggested reason could not be generated.')
    } finally {
      setFlagDraftLoading(false)
    }
  }

  function openFieldEditor(field: ExtractedField) { setFieldToEdit(field); setEditedValue(field.value); setEditedPage(field.page_number) }
  async function saveCorrection() {
    if (!fieldToEdit || !editedValue.trim()) return
    if (await runAction(() => api.updateExtractedField(supplierId, fieldToEdit.id, { value: editedValue.trim(), page_number: editedPage }), 'Correction saved and policy checks refreshed.')) setFieldToEdit(null)
  }

  async function saveDecision() {
    if (!decisionAction) return
    const action = decisionAction
    if (await runAction(() => action === 'approve' ? api.approveSupplier(supplierId) : api.rejectSupplier(supplierId, rejectionReason.trim()), action === 'approve' ? 'Supplier approved and sent to the mock ERP approval workflow.' : 'Supplier rejected.')) {
      setDecisionAction(null); setRejectionReason('')
    }
  }

  async function refreshErpValidation() {
    setErpValidating(true); setErpValidationError('')
    try { setErpValidation(await api.validateErpRecord(supplierId)) }
    catch (validationError) { setErpValidation(null); setErpValidationError(validationError instanceof Error ? validationError.message : 'ERP validation could not be completed.') }
    finally { setErpValidating(false) }
  }

  async function openErpRecord() {
    setBusy(true); setError('')
    try { setErpRecord(await api.getErpRecord(supplierId)); setShowErpRecord(true) }
    catch (recordError) { setError(recordError instanceof Error ? recordError.message : 'ERP record could not be retrieved.') }
    finally { setBusy(false) }
  }

  if (loading) return <Box sx={{ display: 'grid', placeItems: 'center', py: 8 }}><CircularProgress /></Box>
  if (!supplier) return <Alert severity="error">{error || 'Supplier was not found.'}</Alert>

  const filterOptions: Array<{ key: RequirementFilter; label: string; color: 'warning' | 'success' | 'info' | 'error'; description: string }> = [
    { key: 'attention', label: 'Needs attention', color: 'warning', description: 'A mismatch, human judgement, missing evidence, or processing issue needs action.' },
    { key: 'matched', label: 'Ready to confirm', color: 'info', description: 'The checks matched; the reviewer still needs to confirm the original evidence.' },
    { key: 'verified', label: 'Confirmed', color: 'success', description: 'The reviewer confirmed the requirement and its extracted values.' },
    { key: 'flagged', label: 'Flagged', color: 'error', description: 'The reviewer recorded an issue that blocks approval.' },
  ]
  const activeOption = filterOptions.find((option) => option.key === selectedFilter) ?? filterOptions[0]
  const visibleRequirements = orderedEvidence.filter((item) => item.status === selectedFilter)
  const readyRequirements = selectedFilter === 'matched' && !finalized
    ? visibleRequirements.filter(({ document, checks }) => Boolean(
      document
      && document.review_status === 'pending'
      && document.processing_status === 'ready'
      && document.ai_extraction_status === 'ready'
      && document.ai_index_status !== 'failed'
      && checks.length > 0
      && checks.every((check) => policyOutcome(check) === 'matched'),
    )) : []
  const proposedErp = Object.entries(supplier.erp_preview.payload).map(([fieldName, value]) => ({ fieldName, label: erpLabels[fieldName] ?? fieldLabel(fieldName), value: value ?? 'Not provided', source: supplier.erp_preview.sources[fieldName] }))
  const identityErpFields = new Set(['supplier_reference', 'legal_name', 'registered_address', 'country', 'contact_name', 'contact_email', 'category', 'subcategory'])
  const identityErp = proposedErp.filter((item) => identityErpFields.has(item.fieldName))
  const paymentErp = proposedErp.filter((item) => !identityErpFields.has(item.fieldName))
  const reviewSupplier = supplier

  function renderCheck(check: ComplianceResult, document: SupplierDocument | undefined) {
    const outcome = policyOutcome(check)
    const citedFields = Array.isArray(check.evidence.evidence_fields) ? check.evidence.evidence_fields.map((item) => normalizedFieldKey(String(item))) : []
    const savedObserved = Array.isArray(check.evidence.observed_values) ? check.evidence.observed_values as Array<{ field_name?: string; value?: unknown; page_number?: number }> : []
    const observed = savedObserved.length ? savedObserved : reviewSupplier.extracted_fields
      .filter((field) => field.document_id === document?.id && citedFields.includes(normalizedFieldKey(field.field_name)))
      .map((field) => ({ field_name: field.field_name, value: field.value, page_number: field.page_number }))
    const savedExpected = Array.isArray(check.evidence.expected_values) ? check.evidence.expected_values as Array<{ field_name?: string; value?: unknown }> : []
    const portalValues: Record<string, unknown> = { supplier_name: reviewSupplier.name, tax_identifier: reviewSupplier.tax_reference, bank_account_number: reviewSupplier.bank_account_number, bank_ifsc: reviewSupplier.bank_ifsc, contact_email: reviewSupplier.contact_email, country: 'India' }
    const inferredExpected = [...new Set(citedFields)].filter((name) => portalValues[name] != null && portalValues[name] !== '').map((name) => ({ field_name: name, value: portalValues[name] }))
    const expected = savedExpected.length ? savedExpected : inferredExpected.length ? inferredExpected : [{ field_name: 'policy_rule', value: String(check.evidence.check_text ?? 'Review against the policy check.') }]
    const expectedByField = new Map(expected
      .filter((item) => item.field_name && item.field_name !== 'policy_rule')
      .map((item) => [normalizedFieldKey(String(item.field_name)), item]))
    const observedByField = new Map(observed
      .filter((item) => item.field_name)
      .map((item) => [normalizedFieldKey(String(item.field_name)), item]))
    const comparisonFields = [...new Set([...observedByField.keys(), ...expectedByField.keys()])]
      .filter((fieldName) => expectedByField.has(fieldName))
    const method = String(check.evidence.assessment_method ?? 'ai_semantic')
    const methodLabel = method === 'deterministic' ? 'Calculated from extracted values' : method === 'human_required' ? 'Human judgement required' : method === 'reviewer' ? 'Confirmed by reviewer' : 'AI-assisted comparison'
    const checkText = String(check.evidence.check_text ?? check.message)
    const reason = String(check.evidence.ai_reason ?? check.message)
    return (
      <Box key={check.id} sx={{ px: 2, py: 1.75 }}>
        <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1} alignItems={{ sm: 'flex-start' }}>
          <Box><Typography variant="body2" fontWeight={700}>{checkText}</Typography>{reason !== checkText && method !== 'reviewer' && <Typography variant="body2" color="text.secondary" sx={{ mt: .4 }}>{reason}</Typography>}</Box>
          <Stack alignItems={{ sm: 'flex-end' }} sx={{ flexShrink: 0 }}>
            <Typography variant="caption" fontWeight={700} color={outcome === 'matched' ? 'success.dark' : outcome === 'not_matched' ? 'error.dark' : 'warning.dark'}>
              {outcome === 'matched' ? '✓ Matched' : outcome === 'not_matched' ? 'Not matched' : 'Human review'}
            </Typography>
            {method !== 'reviewer' && <Typography variant="caption" color="text.secondary">{methodLabel}</Typography>}
          </Stack>
        </Stack>
        {outcome !== 'matched' && comparisonFields.length > 0 && (
          <Box sx={{ mt: 1.25, border: 1, borderColor: 'divider', borderRadius: 1.5, overflow: 'hidden' }}>
            <Box sx={{ display: { xs: 'none', sm: 'grid' }, gridTemplateColumns: 'minmax(130px, .7fr) minmax(0, 1fr) minmax(0, 1fr)', gap: 1.5, px: 1.25, py: .75, bgcolor: 'action.hover' }}>
              <Typography variant="caption" fontWeight={750}>Field comparison</Typography>
              <Typography variant="caption" fontWeight={750}>Document value</Typography>
              <Typography variant="caption" fontWeight={750}>Portal / expected value</Typography>
            </Box>
            <Stack divider={<Divider flexItem />}>
              {comparisonFields.map((fieldName) => {
                const observedItem = observedByField.get(fieldName)
                const expectedItem = expectedByField.get(fieldName)
                const matches = comparisonValueMatches(fieldName, observedItem?.value, expectedItem?.value)
                return (
                  <Box
                    key={fieldName}
                    sx={{
                      display: 'grid',
                      gridTemplateColumns: { xs: '1fr', sm: 'minmax(130px, .7fr) minmax(0, 1fr) minmax(0, 1fr)' },
                      gap: { xs: .6, sm: 1.5 },
                      px: 1.25,
                      py: 1,
                      bgcolor: matches ? 'background.paper' : 'rgba(211,47,47,.055)',
                    }}
                  >
                    <Stack direction="row" spacing={.75} alignItems="center">
                      <Typography variant="caption" fontWeight={750}>{fieldLabel(fieldName)}</Typography>
                      <Typography variant="caption" fontWeight={750} color={matches ? 'success.dark' : 'error.dark'}>{matches ? '✓ Match' : 'Mismatch'}</Typography>
                    </Stack>
                    <Box>
                      <Typography variant="caption" color="text.secondary" display={{ xs: 'block', sm: 'none' }}>Document value</Typography>
                      <ComparedValue value={observedItem?.value} comparison={expectedItem?.value} highlight={!matches} />
                      {observedItem?.page_number && <Typography component="span" variant="caption" color="text.secondary"> · page {observedItem.page_number}</Typography>}
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary" display={{ xs: 'block', sm: 'none' }}>Portal / expected value</Typography>
                      <ComparedValue value={expectedItem?.value} comparison={observedItem?.value} highlight={!matches} />
                    </Box>
                  </Box>
                )
              })}
            </Stack>
          </Box>
        )}
        {outcome !== 'matched' && comparisonFields.length === 0 && (
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 1, mt: 1.25 }}>
            <Box sx={{ p: 1.25, borderRadius: 1.5, bgcolor: 'rgba(211,47,47,.06)' }}><Typography variant="caption" fontWeight={750} color="error.dark">Observed</Typography>{observed.length ? observed.map((item, index) => <Typography key={`${item.field_name}-${index}`} variant="caption" display="block" sx={{ mt: .4, overflowWrap: 'anywhere' }}>{fieldLabel(String(item.field_name ?? 'value'))}: {item.value == null || item.value === '' ? 'Not found' : String(item.value)}{item.page_number ? ` · page ${item.page_number}` : ''}</Typography>) : <Typography variant="caption" display="block" sx={{ mt: .4 }}>No reliable value was extracted.</Typography>}</Box>
            <Box sx={{ p: 1.25, borderRadius: 1.5, bgcolor: 'action.hover' }}><Typography variant="caption" fontWeight={750}>Expected</Typography>{expected.map((item, index) => <Typography key={`${item.field_name}-${index}`} variant="caption" display="block" sx={{ mt: .4, overflowWrap: 'anywhere' }}>{item.field_name === 'policy_rule' ? '' : `${fieldLabel(String(item.field_name ?? 'value'))}: `}{String(item.value ?? 'Not specified')}</Typography>)}</Box>
          </Box>
        )}
      </Box>
    )
  }

  function renderErpGroup(title: string, items: typeof proposedErp) {
    return (
      <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 2, overflow: 'hidden' }}>
        <Typography fontWeight={750} sx={{ px: 2, py: 1.5, bgcolor: 'action.hover' }}>{title}</Typography>
        <Stack divider={<Divider flexItem />}>
          {items.map((item) => {
            const sourceColor = item.source?.source === 'reviewed_evidence' ? 'success.dark'
              : item.source?.source === 'supplier_entered' ? 'info.dark'
                : item.source?.source === 'not_available' ? 'warning.dark' : 'text.secondary'
            return (
              <Stack key={item.fieldName} direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1.5} sx={{ px: 2, py: 1.25 }}>
                <Typography variant="body2" color="text.secondary">{item.label}</Typography>
                <Box sx={{ minWidth: 0, textAlign: { sm: 'right' } }}>
                  <Typography variant="body2" fontWeight={650} sx={{ overflowWrap: 'anywhere' }}>{String(item.value)}</Typography>
                  <Typography variant="caption" color={sourceColor}>{item.source?.label ?? 'Unknown source'}</Typography>
                </Box>
              </Stack>
            )
          })}
        </Stack>
      </Box>
    )
  }

  return (
    <Stack spacing={3}>
      <Button component={Link} to="/review" startIcon={<ArrowBackRoundedIcon />} sx={{ alignSelf: 'flex-start' }}>Back to reviewer workspace</Button>
      <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={2}>
        <Box><Typography variant="h4">{supplier.name}</Typography><Chip label={`Supplier reference: ${supplierReference(supplier.id)}`} size="small" variant="outlined" sx={{ my: .75 }} /><Typography color="text.secondary">{supplier.category} / {supplier.subcategory} · {supplier.contact_email || 'No contact email'}</Typography></Box>
        <StatusChip status={supplier.status} />
      </Stack>
      {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}
      {notice && <Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
      {finalized && <Alert severity={supplier.status === 'approved' ? 'success' : 'error'} action={supplier.status === 'approved' ? <Button color="inherit" size="small" onClick={() => void openErpRecord()}>View ERP record</Button> : undefined}>{supplier.status === 'approved' ? `Approved and sent to ERP for approval. Vendor ID: ${supplier.vendor_id || supplier.erp_supplier_id}; ERP record ID: ${supplier.erp_record_id}; portal reference: ${supplierReference(supplier.id)}.` : `Rejected: ${supplier.decision_reason}`}{supplier.decided_at && ` Decision recorded ${new Date(supplier.decided_at).toLocaleString()}.`}</Alert>}

      {supplier.category === 'OTHER' && <Card sx={{ border: 1, borderColor: supplier.other_review_completed_at ? 'success.main' : 'warning.main' }}>
        <CardContent sx={{ p: { xs: 2.5, md: 3 } }}>
          <Stack spacing={2.25}>
            <Box><Stack direction="row" spacing={1} alignItems="center"><FactCheckRoundedIcon color="warning" /><Typography variant="h6">Tailored category review</Typography><Chip size="small" color={supplier.other_review_completed_at ? 'success' : 'warning'} label={supplier.other_review_completed_at ? 'Policy / Legal review recorded' : 'Policy / Legal review required'} /></Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mt: .75 }}>The supplier uploaded the three BASE documents because no listed category fit. Use this note to consult Policy and Legal; the case assistant also has this context.</Typography></Box>
            <Box>
              <TextField fullWidth label="Policy / Legal review outcome" value={otherReviewNote} onChange={(event) => setOtherReviewNote(event.target.value)} multiline minRows={3} disabled={finalized} helperText="Saved in PostgreSQL on this supplier's review record, with reviewer and time recorded in the audit trail." />
              {!finalized && <Button variant="contained" color="warning" sx={{ mt: 1.5 }} disabled={busy || otherReviewNote.trim().length < 10} onClick={() => void completeOtherReview()}>{supplier.other_review_completed_at ? 'Update review outcome' : 'Record Policy / Legal review complete'}</Button>}
            </Box>
            <Divider />
            <Box><Typography fontWeight={750}>Verified evidence received by email</Typography><Typography variant="body2" color="text.secondary">Attach documents only after manually checking them. These files are retained separately from AI-processed policy requirements.</Typography></Box>
            {!finalized && <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems={{ md: 'flex-start' }}><TextField fullWidth size="small" label="What did you verify?" value={additionalVerificationNote} onChange={(event) => setAdditionalVerificationNote(event.target.value)} helperText="At least 10 characters; saved in the audit trail." /><Button component="label" variant="outlined" startIcon={busy ? <CircularProgress size={16} /> : <AttachFileRoundedIcon />} disabled={busy || additionalVerificationNote.trim().length < 10} sx={{ minWidth: 220 }}>{busy ? 'Attaching…' : 'Attach verified evidence'}<input hidden type="file" accept="application/pdf,image/png,image/jpeg,text/plain,.pdf,.png,.jpg,.jpeg,.txt" onChange={(event) => void uploadAdditionalDocument(event)} /></Button></Stack>}
            {supplier.additional_documents.length > 0 && <Stack spacing={1}>{supplier.additional_documents.map((document) => <Stack key={document.id} direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={1} sx={{ p: 1.5, border: 1, borderColor: 'divider', borderRadius: 1.5 }}><Box><Typography fontWeight={650}>{document.filename}</Typography><Typography variant="caption" color="text.secondary">Verified by {document.uploaded_by} · {new Date(document.verified_at).toLocaleString()} · {document.verification_note}</Typography></Box><Stack direction="row" spacing={.5}><Button size="small" onClick={() => void viewAdditionalDocument(document.id)}>View</Button>{!finalized && <Button size="small" color="error" startIcon={<DeleteOutlineRoundedIcon />} disabled={busy} onClick={() => setAdditionalDocumentToDelete(document.id)}>Delete</Button>}</Stack></Stack>)}</Stack>}
            <Box sx={{ p: 2, bgcolor: 'action.hover', borderRadius: 2 }}><Typography variant="caption" color="text.secondary" fontWeight={700}>SUPPLIER SERVICE NOTE</Typography><Typography sx={{ mt: .5, whiteSpace: 'pre-wrap' }}>{supplier.service_description || 'No description was provided.'}</Typography></Box>
            <Alert severity="info">AI extracts ERP-useful suggestions from these files, but no compliance checks are created because the evidence was manually reviewed.</Alert>
          </Stack>
        </CardContent>
      </Card>}

      <Card>
        <CardContent sx={{ p: { xs: 2.5, md: 3 } }}>
          <Stack direction={{ xs: 'column', lg: 'row' }} spacing={2.5} alignItems={{ lg: 'center' }}>
            <Box sx={{ minWidth: { lg: 230 } }}>
              <Stack direction="row" spacing={1} alignItems="center"><AutoAwesomeRoundedIcon color="primary" /><Typography variant="h6">Document processing</Typography></Stack>
              <Typography color="text.secondary" variant="body2" sx={{ mt: .5 }}>Extraction, indexing, and technical readiness.</Typography>
            </Box>
            <Stack spacing={.75} sx={{ flex: 1 }}>
              {findings.map((finding, index) => <Alert key={`${finding.text}-${index}`} severity={finding.severity} sx={{ flex: 1, py: .25, overflowWrap: 'anywhere' }}>{finding.text}</Alert>)}
            </Stack>
            <Box sx={{ minWidth: { lg: 245 }, textAlign: { lg: 'right' } }}>
              {latestProcessingRun && <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>Last run {new Date(latestProcessingRun.created_at).toLocaleString()} · {(latestProcessingRun.latency_ms / 1000).toFixed(1)}s</Typography>}
              {!finalized && <Button variant="outlined" startIcon={busy || processingActive ? <CircularProgress size={17} /> : <AutoAwesomeRoundedIcon />} disabled={busy || processingActive} onClick={() => void runSupplierAnalysis()}>{busy || processingActive ? 'Analyzing documents...' : !latestProcessingRun ? 'Run AI analysis' : latestProcessingRun.status === 'failed' ? 'Retry analysis' : 'Refresh AI analysis'}</Button>}
            </Box>
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent sx={{ p: { xs: 2.5, md: 4 } }}>
          <Stack direction="row" spacing={1} alignItems="center"><FactCheckRoundedIcon color="primary" /><Typography variant="h6">Requirement review</Typography></Stack>
          <Typography color="text.secondary" variant="body2" sx={{ mt: .5 }}>Review the document, policy findings, and extracted values together. Confirm or flag the requirement without leaving its card.</Typography>
          {supplier.category === 'OTHER' && <Box sx={{ mt: 2.5, p: 2, border: 1, borderColor: 'info.main', borderRadius: 2.5, bgcolor: 'rgba(2,136,209,.04)' }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1}>
              <Box><Typography fontWeight={750}>Manually reviewed supporting evidence</Typography><Typography variant="body2" color="text.secondary">Reviewer-added files are visible here for completeness. They produce ERP suggestions only and do not create policy checks.</Typography></Box>
              <Chip size="small" color={supplier.additional_documents.length ? 'success' : 'default'} label={`${supplier.additional_documents.length} file${supplier.additional_documents.length === 1 ? '' : 's'} added`} sx={{ alignSelf: { xs: 'flex-start', sm: 'center' } }} />
            </Stack>
            {supplier.additional_documents.length === 0 ? <Alert severity="info" sx={{ mt: 1.5 }}>No additional evidence has been attached by the reviewer.</Alert> : <Stack spacing={1.25} sx={{ mt: 1.5 }}>
              {supplier.additional_documents.map((document) => <Box key={document.id} sx={{ p: 1.5, bgcolor: 'background.paper', border: 1, borderColor: 'divider', borderRadius: 1.5 }}>
                <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={1}>
                  <Box><Typography fontWeight={700}>{document.filename}</Typography><Typography variant="caption" color="text.secondary">Manual verification: {document.verification_note}</Typography></Box>
                  <Stack direction="row" spacing={.5} alignItems="center"><Chip size="small" color={document.ai_extraction_status === 'ready' ? 'success' : document.ai_extraction_status === 'failed' ? 'warning' : 'default'} label={`ERP extraction ${displayStatus(document.ai_extraction_status)}`} /><Button size="small" onClick={() => void viewAdditionalDocument(document.id)}>View</Button>{!finalized && <Button size="small" color="error" onClick={() => setAdditionalDocumentToDelete(document.id)}>Delete</Button>}</Stack>
                </Stack>
                {document.ai_extraction_error && <Typography variant="caption" color="warning.dark" display="block" sx={{ mt: .75 }}>{document.ai_extraction_error} The manually verified file remains valid.</Typography>}
                {document.erp_fields.length > 0 && <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0, 1fr))' }, gap: 1, mt: 1.25 }}>{document.erp_fields.map((field) => <Box key={field.field_name} sx={{ p: 1, borderRadius: 1, bgcolor: 'action.hover' }}><Typography variant="caption" color="text.secondary" fontWeight={700}>{fieldLabel(field.field_name)}</Typography><Typography variant="body2" fontWeight={650} sx={{ overflowWrap: 'anywhere' }}>{field.value}</Typography><Typography variant="caption" color={field.confidence >= .75 ? 'text.secondary' : 'warning.dark'}>page {field.page_number} · {Math.round(field.confidence * 100)}% AI confidence · {field.confidence >= .75 ? 'available to ERP' : 'below ERP-use threshold'}</Typography></Box>)}</Box>}
              </Box>)}
            </Stack>}
          </Box>}
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' }, gap: 1, my: 2.5 }}>
            {filterOptions.map((option) => {
              const count = orderedEvidence.filter((item) => item.status === option.key).length
              return <ButtonBase key={option.key} aria-pressed={selectedFilter === option.key} onClick={() => setSelectedFilter(option.key)} sx={{ p: 1.4, border: 1, borderColor: `${option.color}.main`, borderRadius: 2, bgcolor: selectedFilter === option.key ? 'action.selected' : 'background.paper', display: 'block', textAlign: 'left', boxShadow: selectedFilter === option.key ? 2 : 0 }}><Typography variant="h5" color={`${option.color}.dark`} fontWeight={750}>{count}</Typography><Typography variant="body2" fontWeight={700}>{option.label}</Typography></ButtonBase>
            })}
          </Box>
          <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={1.5}>
            <Box><Typography fontWeight={750}>{activeOption.label}</Typography><Typography variant="caption" color="text.secondary">{activeOption.description}</Typography></Box>
            {selectedFilter === 'matched' && readyRequirements.length > 0 && <Button variant="contained" color="success" startIcon={<DoneAllRoundedIcon />} disabled={busy} onClick={() => setConfirmAllOpen(true)}>Confirm all ({readyRequirements.length})</Button>}
          </Stack>
          <Stack spacing={2} sx={{ mt: 2 }}>
            {visibleRequirements.length === 0 ? <Alert severity="info">No requirements in this group.</Alert> : visibleRequirements.map(({ requirement, document, checks, fields, status }) => {
              const requirementKey = requirement.document_type
              const extractedExpanded = expandedRequirements.has(requirementKey)
              const checksExpanded = checkVisibility[requirementKey] ?? status !== 'verified'
              const hasMismatch = checks.some((check) => policyOutcome(check) === 'not_matched')
              const analysisReady = document?.ai_extraction_status === 'ready'
              const canConfirm = Boolean(document && analysisReady && !hasMismatch && !finalized)
              const blockedReason = !document ? 'The required document is missing.' : !analysisReady ? 'Run or retry document analysis first.' : hasMismatch ? 'Correct the extracted value or flag the requirement before confirming.' : ''
              const statusLabel = filterOptions.find((option) => option.key === status)?.label
              return (
                <Box key={requirementKey} sx={{ border: 1, borderColor: status === 'flagged' ? 'error.main' : status === 'attention' ? 'warning.main' : 'divider', borderRadius: 2.5, overflow: 'hidden' }}>
                  <Box sx={{ p: 2, bgcolor: 'action.hover' }}>
                    <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={1.5}>
                      <Box sx={{ minWidth: 0 }}>
                        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap><Typography fontWeight={750}>{requirement.label}</Typography><Typography variant="caption" color="text.secondary">{requirement.requirement_id}</Typography><Chip size="small" color={status === 'verified' ? 'success' : status === 'flagged' ? 'error' : status === 'attention' ? 'warning' : 'info'} label={statusLabel} /></Stack>
                        <Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>{requirement.accepted_evidence}</Typography>
                        {document && <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: .5, overflowWrap: 'anywhere' }}>{document.filename} · {document.page_count} page(s) · version {document.revision}</Typography>}
                        {document?.ocr_pages.length ? <Typography variant="caption" color="info.dark" display="block">OCR-derived page{document.ocr_pages.length === 1 ? '' : 's'}: {document.ocr_pages.join(', ')}{document.ocr_language ? ` · ${document.ocr_language}` : ''}</Typography> : null}
                        {document?.ocr_quality_score != null && <Stack direction="row" spacing={.75} alignItems="center" sx={{ mt: .5 }} flexWrap="wrap" useFlexGap>
                          <Chip
                            size="small"
                            color={document.ocr_quality_status === 'good' ? 'success' : document.ocr_quality_status === 'review' ? 'warning' : 'error'}
                            label={`OCR reliability ${Math.round(document.ocr_quality_score)}%`}
                          />
                          <Typography variant="caption" color="text.secondary">Extraction reliability only—not an authenticity score.</Typography>
                        </Stack>}
                        {document?.ocr_quality_status === 'review' && <Alert severity="warning" sx={{ mt: .75, py: .25 }}>Manually compare every OCR-derived value with the original. Correct any OCR error below before confirming this requirement.</Alert>}
                        {document?.ocr_warnings.map((warning) => <Typography key={warning} variant="caption" color="warning.dark" display="block">OCR warning: {warning}</Typography>)}
                        {document?.review_status === 'disputed' && document.review_comment && <Typography variant="caption" color="error" display="block">Flag reason: {document.review_comment}</Typography>}
                      </Box>
                      <Stack alignItems={{ md: 'flex-end' }} spacing={.5} sx={{ flexShrink: 0 }}>
                        <Button size="small" color="inherit" endIcon={checksExpanded ? <ExpandLessRoundedIcon /> : <ExpandMoreRoundedIcon />} onClick={() => setCheckVisibility((current) => ({ ...current, [requirementKey]: !checksExpanded }))}>{checksExpanded ? 'Hide checks' : `Show checks (${checks.length})`}</Button>
                        {document && <Typography variant="caption" color={document.ai_extraction_status === 'failed' || document.processing_status === 'failed' ? 'error' : 'text.secondary'}>Document {displayStatus(document.processing_status)} · extraction {displayStatus(document.ai_extraction_status)}</Typography>}
                        {document ? <Stack direction="row" spacing={.5}><Button size="small" startIcon={<DescriptionRoundedIcon />} onClick={() => void viewOriginal(document.id)}>View original</Button><Button size="small" onClick={() => void downloadFile(document)}>Download</Button>{!finalized && document.processing_status === 'failed' && <Button size="small" disabled={busy} onClick={() => void retryTextExtraction(document)}>Retry OCR</Button>}{!finalized && document.processing_status === 'ready' && (document.ai_extraction_status === 'failed' || document.ai_index_status === 'failed') && <Button size="small" disabled={busy} onClick={() => void retryDocument(document)}>Retry AI</Button>}</Stack> : <Typography variant="caption" color="error">Required document missing</Typography>}
                      </Stack>
                    </Stack>
                  </Box>
                  {checksExpanded && (checks.length ? <Stack divider={<Divider flexItem />}>{checks.map((check) => renderCheck(check, document))}</Stack> : <Alert severity="warning" sx={{ m: 2 }}>Policy analysis is not available for this requirement yet.</Alert>)}
                  <Divider />
                  <Box sx={{ px: 2, py: 1.25 }}>
                    <Button size="small" endIcon={extractedExpanded ? <ExpandLessRoundedIcon /> : <ExpandMoreRoundedIcon />} onClick={() => setExpandedRequirements((current) => { const next = new Set(current); if (next.has(requirementKey)) next.delete(requirementKey); else next.add(requirementKey); return next })}>Extracted values ({fields.length})</Button>
                    {extractedExpanded && <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0, 1fr))' }, gap: 1, mt: 1.25 }}>{fields.length ? fields.map((field) => <Box key={field.id} sx={{ p: 1.25, border: 1, borderColor: field.review_status === 'disputed' ? 'error.main' : 'divider', borderRadius: 1.5 }}><Stack direction="row" justifyContent="space-between" spacing={1}><Typography variant="caption" color="text.secondary" fontWeight={700}>{fieldLabel(field.field_name)}</Typography><Stack direction="row" spacing={.25} alignItems="center"><Typography variant="caption" color={field.review_status === 'disputed' ? 'error' : 'text.secondary'}>{displayStatus(field.review_status)}</Typography>{!finalized && <Tooltip title={document?.ocr_pages.includes(field.page_number) ? 'Correct OCR value after checking the original image' : 'Correct extracted value'}><IconButton size="small" onClick={() => openFieldEditor(field)}><EditRoundedIcon fontSize="small" /></IconButton></Tooltip>}</Stack></Stack><Typography variant="body2" fontWeight={650} sx={{ mt: .75, overflowWrap: 'anywhere' }}>{field.value}</Typography><Typography variant="caption" color={document?.ocr_pages.includes(field.page_number) ? 'info.dark' : 'text.secondary'}>page {field.page_number}{document?.ocr_pages.includes(field.page_number) ? ' · OCR-derived' : ''} · {field.review_status === 'corrected' ? 'Reviewer-corrected' : `${Math.round(field.confidence * 100)}% AI confidence`}</Typography></Box>) : <Alert severity="info">No values were extracted from this document.</Alert>}</Box>}
                  </Box>
                  {!finalized && document && status !== 'verified' && <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="flex-end" spacing={1} sx={{ px: 2, pb: 2 }}><Button color="error" variant="outlined" startIcon={<FlagRoundedIcon />} disabled={busy || flagDraftLoading} onClick={() => void openFlagDialog(document.id)}>Flag with AI draft</Button><Tooltip title={canConfirm ? 'Confirm the document, extracted values, and policy checks together.' : blockedReason}><span><Button color="success" variant="contained" startIcon={<CheckCircleRoundedIcon />} disabled={!canConfirm || busy} onClick={() => void confirmRequirement(document, requirement)}>Confirm requirement</Button></span></Tooltip></Stack>}
                  {status === 'verified' && document?.reviewed_at && <Typography variant="caption" color="text.secondary" display="block" textAlign="right" sx={{ px: 2, pb: 1.5 }}>Confirmed {new Date(document.reviewed_at).toLocaleString()}{document.reviewed_by ? ` by ${document.reviewed_by}` : ''}</Typography>}
                </Box>
              )
            })}
          </Stack>
          {history.length > 0 && <Box sx={{ mt: 3, pt: 2, borderTop: 1, borderColor: 'divider' }}><Typography fontWeight={700}>Previous document versions</Typography><Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Retained originals remain available for audit.</Typography>{history.map((item) => <Stack key={item.id} direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={1} sx={{ py: .75 }}><Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>{item.filename} · version {item.revision}</Typography><Stack direction="row"><Button size="small" onClick={() => void viewOriginal(item.id)}>View</Button><Button size="small" onClick={() => void downloadFile(item)}>Download</Button></Stack></Stack>)}</Box>}
        </CardContent>
      </Card>

      <Card><CardContent sx={{ p: { xs: 3, md: 4 } }}><Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2}><Box><Typography variant="h6">Proposed ERP submission</Typography><Typography color="text.secondary" variant="body2">This is the exact payload that will be sent to the downstream ERP approval workflow. Only reviewed or corrected evidence overrides supplier-entered data.</Typography></Box><Button variant="outlined" size="small" disabled={erpValidating || finalized} onClick={() => void refreshErpValidation()}>{erpValidating ? 'Validating...' : 'Validate with ERP'}</Button></Stack>{erpValidationError && <Alert severity="error" sx={{ my: 2 }}>{erpValidationError} Nothing was sent to ERP; retry is safe.</Alert>}{erpValidation?.valid && <Alert severity="success" sx={{ my: 2 }}>ERP validation passed.{erpValidation.warnings.length ? ` ${erpValidation.warnings.length} optional field warning${erpValidation.warnings.length === 1 ? '' : 's'} will not block the hand-off.` : ''}</Alert>}{erpValidation && !erpValidation.valid && <Alert severity="error" sx={{ my: 2 }}><Typography fontWeight={700}>ERP validation must be resolved before approval.</Typography>{erpValidation.errors.map((item) => <Typography key={`${item.field}-${item.code}`} variant="body2">• {item.message}</Typography>)}</Alert>}<Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'repeat(2, minmax(0, 1fr))' }, gap: 2 }}>{renderErpGroup('Identity and classification', identityErp)}{renderErpGroup('Payment, banking and risk', paymentErp)}</Box>{erpValidation?.warnings.length ? <Box sx={{ mt: 1.5 }}>{erpValidation.warnings.map((item) => <Typography key={`${item.field}-${item.code}`} variant="caption" color="text.secondary" display="block">Optional: {item.message}</Typography>)}</Box> : null}{supplier.erp_payload && <Alert severity="success" sx={{ mt: 2 }} action={<Button color="inherit" size="small" onClick={() => void openErpRecord()}>Retrieve from ERP</Button>}>The exact ERP payload was retained with this approval for audit.</Alert>}</CardContent></Card>

      <Card><CardContent sx={{ p: { xs: 3, md: 4 } }}><Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ md: 'center' }} spacing={2}><Alert severity={approvalReady ? 'success' : 'warning'} sx={{ flex: 1 }}>{approvalReady ? 'Every requirement is confirmed, policy checks pass, the tailored review is complete when applicable, and ERP validation is complete.' : !complianceReady ? 'Approval stays blocked until every requirement is confirmed and all policy checks pass.' : !otherReviewReady ? 'Record the Policy and Legal review outcome before sending this Other-category supplier to ERP.' : erpValidationError ? 'Policy review is complete, but the ERP is unavailable. Retry validation safely.' : 'Policy review is complete. Resolve the ERP validation results before approval.'}</Alert><Stack direction="row" spacing={1}><Button color="error" variant="outlined" startIcon={<BlockRoundedIcon />} disabled={finalized || busy} onClick={() => setDecisionAction('reject')}>Reject</Button><Button color="success" variant="contained" startIcon={<HowToRegRoundedIcon />} disabled={!approvalReady || finalized || busy} onClick={() => setDecisionAction('approve')}>Approve and send to ERP for approval</Button></Stack></Stack></CardContent></Card>

      <Dialog open={fieldToEdit !== null} onClose={() => !busy && setFieldToEdit(null)} fullWidth maxWidth="sm"><DialogTitle>Correct OCR or extracted value</DialogTitle><DialogContent><Stack spacing={2} sx={{ pt: 1 }}><Alert severity="warning">Open the original evidence and copy exactly what is visible. This correction is attributed to the reviewer and retained in the audit trail.</Alert><TextField label={fieldToEdit ? fieldLabel(fieldToEdit.field_name) : 'Value'} value={editedValue} onChange={(event) => setEditedValue(event.target.value)} multiline minRows={2} autoFocus /><TextField label="Source page" type="number" value={editedPage} onChange={(event) => setEditedPage(Math.max(1, Number(event.target.value)))} slotProps={{ htmlInput: { min: 1 } }} /><Alert severity="info">Saving records the field, source page and reviewer as a human-reviewed correction, then recalculates the policy checks.</Alert></Stack></DialogContent><DialogActions><Button onClick={() => setFieldToEdit(null)} disabled={busy}>Cancel</Button><Button variant="contained" onClick={() => void saveCorrection()} disabled={busy || !editedValue.trim()}>{busy ? 'Saving...' : 'Save correction'}</Button></DialogActions></Dialog>
      <Dialog open={flagDocumentId !== null} onClose={() => !busy && !flagDraftLoading && setFlagDocumentId(null)} fullWidth maxWidth="sm"><DialogTitle>Flag requirement for follow-up</DialogTitle><DialogContent><Stack spacing={2} sx={{ pt: 1 }}><DialogContentText>The portal drafts a grounded reason from the current policy findings. Review or edit it before saving; the human reviewer remains responsible for the flag.</DialogContentText>{flagDraftLoading ? <Alert severity="info" icon={<CircularProgress size={18} />}>Drafting a reason from this document’s findings and the applicable policy…</Alert> : flagDraftSource && <Alert severity={flagDraftSource === 'ai_rag' ? 'success' : 'info'}>{flagDraftSource === 'ai_rag' ? 'AI draft generated from the calculated findings and retrieved policy.' : 'A safe draft was generated from the calculated findings.'}</Alert>}<TextField label="Reason" value={flagReason} onChange={(event) => setFlagReason(event.target.value)} multiline minRows={3} autoFocus disabled={flagDraftLoading} /></Stack></DialogContent><DialogActions><Button onClick={() => { setFlagDocumentId(null); setFlagDraftSource(null) }} disabled={busy || flagDraftLoading}>Cancel</Button><Button color="error" variant="contained" onClick={() => void submitFlag()} disabled={busy || flagDraftLoading || flagReason.trim().length < 5}>{busy ? 'Saving...' : 'Flag requirement'}</Button></DialogActions></Dialog>
      <Dialog open={confirmAllOpen} onClose={() => !busy && setConfirmAllOpen(false)} fullWidth maxWidth="sm"><DialogTitle>Confirm all ready requirements?</DialogTitle><DialogContent><Stack spacing={2} sx={{ pt: 1 }}><DialogContentText>This will confirm {readyRequirements.length} requirement{readyRequirements.length === 1 ? '' : 's'} whose policy checks are matched and whose processing is complete.</DialogContentText><Alert severity="warning">Confirm only after comparing these documents with their extracted values. Items requiring OCR or human attention are excluded automatically.</Alert></Stack></DialogContent><DialogActions><Button onClick={() => setConfirmAllOpen(false)} disabled={busy}>Cancel</Button><Button color="success" variant="contained" startIcon={busy ? <CircularProgress size={17} /> : <DoneAllRoundedIcon />} onClick={() => void confirmAllReady()} disabled={busy || readyRequirements.length === 0}>{busy ? 'Confirming…' : `Confirm ${readyRequirements.length}`}</Button></DialogActions></Dialog>
      <Dialog open={decisionAction !== null} onClose={() => !busy && setDecisionAction(null)} fullWidth maxWidth="sm"><DialogTitle>{decisionAction === 'approve' ? 'Approve and send to ERP for approval?' : 'Reject supplier?'}</DialogTitle><DialogContent>{decisionAction === 'approve' ? <DialogContentText>This records the human decision, submits the proposed supplier record to the mock ERP approval workflow, and locks the review. The portal reference remains the onboarding identifier; the downstream ERP workflow returns a separate record ID and final Vendor ID for the Vendor Master.</DialogContentText> : <Stack spacing={2} sx={{ pt: 1 }}><DialogContentText>Provide an auditable rejection reason. Nothing will be sent to ERP.</DialogContentText><TextField label="Rejection reason" value={rejectionReason} onChange={(event) => setRejectionReason(event.target.value)} multiline minRows={3} autoFocus /></Stack>}</DialogContent><DialogActions><Button onClick={() => setDecisionAction(null)} disabled={busy}>Cancel</Button><Button color={decisionAction === 'approve' ? 'success' : 'error'} variant="contained" onClick={() => void saveDecision()} disabled={busy || (decisionAction === 'reject' && rejectionReason.trim().length < 10)}>{busy ? 'Saving decision...' : decisionAction === 'approve' ? 'Approve and send' : 'Confirm rejection'}</Button></DialogActions></Dialog>
      <Dialog open={additionalDocumentToDelete !== null} onClose={() => !busy && setAdditionalDocumentToDelete(null)} fullWidth maxWidth="sm"><DialogTitle>Delete reviewer-added evidence?</DialogTitle><DialogContent><DialogContentText>The file and its AI-extracted ERP suggestions will be removed. If a Policy and Legal outcome was already recorded, it will be cleared so the decision can be recorded again against the correct evidence.</DialogContentText></DialogContent><DialogActions><Button onClick={() => setAdditionalDocumentToDelete(null)} disabled={busy}>Cancel</Button><Button color="error" variant="contained" startIcon={<DeleteOutlineRoundedIcon />} disabled={busy} onClick={() => void deleteAdditionalDocument()}>{busy ? 'Deleting…' : 'Delete evidence'}</Button></DialogActions></Dialog>
      <ErpRecordDialog open={showErpRecord} record={erpRecord} onClose={() => setShowErpRecord(false)} />
    </Stack>
  )
}
