import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded'
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded'
import BlockRoundedIcon from '@mui/icons-material/BlockRounded'
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded'
import DescriptionRoundedIcon from '@mui/icons-material/DescriptionRounded'
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
import { useCallback, useEffect, useMemo, useState } from 'react'
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
  if (!document || document.ai_extraction_status === 'failed' || document.ai_index_status === 'failed') return 'attention'
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

  const loadSupplier = useCallback(async () => {
    try {
      const [detail, archived] = await Promise.all([api.getSupplier(supplierId), api.reviewerDocumentHistory(supplierId)])
      setSupplier(detail)
      setHistory(archived)
      setErpValidating(true)
      try {
        setErpValidation(await api.validateErpRecord(supplierId))
        setErpValidationError('')
      } catch (validationError) {
        setErpValidation(null)
        setErpValidationError(validationError instanceof Error ? validationError.message : 'ERP validation could not be completed.')
      } finally { setErpValidating(false) }
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
  const complianceReady = Boolean(supplier?.compliance_results.length && supplier.compliance_results.every((result) => result.status === 'pass'))
  const approvalReady = complianceReady && Boolean(erpValidation?.valid)

  const findings = useMemo(() => {
    if (!supplier) return []
    const messages: Array<{ severity: 'error' | 'warning' | 'success' | 'info'; text: string }> = []
    if (!latestProcessingRun) return [{ severity: 'info' as const, text: 'AI document analysis has not run yet.' }]
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
  }, [latestProcessingRun, supplier])

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

  async function confirmRequirement(document: SupplierDocument, requirement: RequirementItem) {
    await runAction(
      () => api.reviewEvidence(supplierId, document.id, 'verify'),
      `${requirement.label} confirmed. Its document, extracted values, and policy checks were updated together.`,
    )
  }

  async function submitFlag() {
    if (!flagDocumentId || flagReason.trim().length < 5) return
    if (await runAction(() => api.reviewEvidence(supplierId, flagDocumentId, 'dispute', flagReason.trim()), 'The requirement was flagged and will block approval until resolved.')) {
      setFlagDocumentId(null); setFlagReason('')
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
    if (await runAction(() => action === 'approve' ? api.approveSupplier(supplierId) : api.rejectSupplier(supplierId, rejectionReason.trim()), action === 'approve' ? 'Supplier approved and sent to the mock ERP.' : 'Supplier rejected.')) {
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
      {finalized && <Alert severity={supplier.status === 'approved' ? 'success' : 'error'} action={supplier.status === 'approved' ? <Button color="inherit" size="small" onClick={() => void openErpRecord()}>View ERP record</Button> : undefined}>{supplier.status === 'approved' ? `Approved and created in the mock ERP as ${supplier.erp_supplier_id}.` : `Rejected: ${supplier.decision_reason}`}{supplier.decided_at && ` Decision recorded ${new Date(supplier.decided_at).toLocaleString()}.`}</Alert>}

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
              {!finalized && <Button variant="outlined" startIcon={busy ? <CircularProgress size={17} /> : <AutoAwesomeRoundedIcon />} disabled={busy} onClick={() => void runSupplierAnalysis()}>{busy ? 'Analyzing documents...' : !latestProcessingRun ? 'Run AI analysis' : latestProcessingRun.status === 'failed' ? 'Retry analysis' : 'Refresh AI analysis'}</Button>}
            </Box>
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent sx={{ p: { xs: 2.5, md: 4 } }}>
          <Stack direction="row" spacing={1} alignItems="center"><FactCheckRoundedIcon color="primary" /><Typography variant="h6">Requirement review</Typography></Stack>
          <Typography color="text.secondary" variant="body2" sx={{ mt: .5 }}>Review the document, policy findings, and extracted values together. Confirm or flag the requirement without leaving its card.</Typography>
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' }, gap: 1, my: 2.5 }}>
            {filterOptions.map((option) => {
              const count = orderedEvidence.filter((item) => item.status === option.key).length
              return <ButtonBase key={option.key} aria-pressed={selectedFilter === option.key} onClick={() => setSelectedFilter(option.key)} sx={{ p: 1.4, border: 1, borderColor: `${option.color}.main`, borderRadius: 2, bgcolor: selectedFilter === option.key ? 'action.selected' : 'background.paper', display: 'block', textAlign: 'left', boxShadow: selectedFilter === option.key ? 2 : 0 }}><Typography variant="h5" color={`${option.color}.dark`} fontWeight={750}>{count}</Typography><Typography variant="body2" fontWeight={700}>{option.label}</Typography></ButtonBase>
            })}
          </Box>
          <Typography fontWeight={750}>{activeOption.label}</Typography><Typography variant="caption" color="text.secondary">{activeOption.description}</Typography>
          <Stack spacing={2} sx={{ mt: 2 }}>
            {visibleRequirements.length === 0 ? <Alert severity="info">No requirements in this group.</Alert> : visibleRequirements.map(({ requirement, document, checks, fields, status }) => {
              const extractedExpanded = expandedRequirements.has(requirement.requirement_id)
              const checksExpanded = checkVisibility[requirement.requirement_id] ?? status !== 'verified'
              const hasMismatch = checks.some((check) => policyOutcome(check) === 'not_matched')
              const analysisReady = document?.ai_extraction_status === 'ready'
              const canConfirm = Boolean(document && analysisReady && !hasMismatch && !finalized)
              const blockedReason = !document ? 'The required document is missing.' : !analysisReady ? 'Run or retry document analysis first.' : hasMismatch ? 'Correct the extracted value or flag the requirement before confirming.' : ''
              const statusLabel = filterOptions.find((option) => option.key === status)?.label
              return (
                <Box key={requirement.requirement_id} sx={{ border: 1, borderColor: status === 'flagged' ? 'error.main' : status === 'attention' ? 'warning.main' : 'divider', borderRadius: 2.5, overflow: 'hidden' }}>
                  <Box sx={{ p: 2, bgcolor: 'action.hover' }}>
                    <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={1.5}>
                      <Box sx={{ minWidth: 0 }}>
                        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap><Typography fontWeight={750}>{requirement.label}</Typography><Typography variant="caption" color="text.secondary">{requirement.requirement_id}</Typography><Chip size="small" color={status === 'verified' ? 'success' : status === 'flagged' ? 'error' : status === 'attention' ? 'warning' : 'info'} label={statusLabel} /></Stack>
                        <Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>{requirement.accepted_evidence}</Typography>
                        {document && <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: .5, overflowWrap: 'anywhere' }}>{document.filename} · {document.page_count} page(s) · version {document.revision}</Typography>}
                        {document?.review_status === 'disputed' && document.review_comment && <Typography variant="caption" color="error" display="block">Flag reason: {document.review_comment}</Typography>}
                      </Box>
                      <Stack alignItems={{ md: 'flex-end' }} spacing={.5} sx={{ flexShrink: 0 }}>
                        <Button size="small" color="inherit" endIcon={checksExpanded ? <ExpandLessRoundedIcon /> : <ExpandMoreRoundedIcon />} onClick={() => setCheckVisibility((current) => ({ ...current, [requirement.requirement_id]: !checksExpanded }))}>{checksExpanded ? 'Hide checks' : `Show checks (${checks.length})`}</Button>
                        {document && <Typography variant="caption" color={document.ai_extraction_status === 'failed' || document.processing_status === 'failed' ? 'error' : 'text.secondary'}>Document {displayStatus(document.processing_status)} · extraction {displayStatus(document.ai_extraction_status)}</Typography>}
                        {document ? <Stack direction="row" spacing={.5}><Button size="small" startIcon={<DescriptionRoundedIcon />} onClick={() => void viewOriginal(document.id)}>View original</Button><Button size="small" onClick={() => void downloadFile(document)}>Download</Button>{!finalized && (document.ai_extraction_status === 'failed' || document.ai_index_status === 'failed') && <Button size="small" disabled={busy} onClick={() => void retryDocument(document)}>Retry AI</Button>}</Stack> : <Typography variant="caption" color="error">Required document missing</Typography>}
                      </Stack>
                    </Stack>
                  </Box>
                  {checksExpanded && (checks.length ? <Stack divider={<Divider flexItem />}>{checks.map((check) => renderCheck(check, document))}</Stack> : <Alert severity="warning" sx={{ m: 2 }}>Policy analysis is not available for this requirement yet.</Alert>)}
                  <Divider />
                  <Box sx={{ px: 2, py: 1.25 }}>
                    <Button size="small" endIcon={extractedExpanded ? <ExpandLessRoundedIcon /> : <ExpandMoreRoundedIcon />} onClick={() => setExpandedRequirements((current) => { const next = new Set(current); if (next.has(requirement.requirement_id)) next.delete(requirement.requirement_id); else next.add(requirement.requirement_id); return next })}>Extracted values ({fields.length})</Button>
                    {extractedExpanded && <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0, 1fr))' }, gap: 1, mt: 1.25 }}>{fields.length ? fields.map((field) => <Box key={field.id} sx={{ p: 1.25, border: 1, borderColor: field.review_status === 'disputed' ? 'error.main' : 'divider', borderRadius: 1.5 }}><Stack direction="row" justifyContent="space-between" spacing={1}><Typography variant="caption" color="text.secondary" fontWeight={700}>{fieldLabel(field.field_name)}</Typography><Stack direction="row" spacing={.25} alignItems="center"><Typography variant="caption" color={field.review_status === 'disputed' ? 'error' : 'text.secondary'}>{displayStatus(field.review_status)}</Typography>{!finalized && <Tooltip title="Correct value"><IconButton size="small" onClick={() => openFieldEditor(field)}><EditRoundedIcon fontSize="small" /></IconButton></Tooltip>}</Stack></Stack><Typography variant="body2" fontWeight={650} sx={{ mt: .75, overflowWrap: 'anywhere' }}>{field.value}</Typography><Typography variant="caption" color="text.secondary">page {field.page_number} · {Math.round(field.confidence * 100)}% AI confidence</Typography></Box>) : <Alert severity="info">No values were extracted from this document.</Alert>}</Box>}
                  </Box>
                  {!finalized && document && status !== 'verified' && <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="flex-end" spacing={1} sx={{ px: 2, pb: 2 }}><Button color="error" variant="outlined" startIcon={<FlagRoundedIcon />} disabled={busy} onClick={() => setFlagDocumentId(document.id)}>Flag with reason</Button><Tooltip title={canConfirm ? 'Confirm the document, extracted values, and policy checks together.' : blockedReason}><span><Button color="success" variant="contained" startIcon={<CheckCircleRoundedIcon />} disabled={!canConfirm || busy} onClick={() => void confirmRequirement(document, requirement)}>Confirm requirement</Button></span></Tooltip></Stack>}
                  {status === 'verified' && document?.reviewed_at && <Typography variant="caption" color="text.secondary" display="block" textAlign="right" sx={{ px: 2, pb: 1.5 }}>Confirmed {new Date(document.reviewed_at).toLocaleString()}{document.reviewed_by ? ` by ${document.reviewed_by}` : ''}</Typography>}
                </Box>
              )
            })}
          </Stack>
          {history.length > 0 && <Box sx={{ mt: 3, pt: 2, borderTop: 1, borderColor: 'divider' }}><Typography fontWeight={700}>Previous document versions</Typography><Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Retained originals remain available for audit.</Typography>{history.map((item) => <Stack key={item.id} direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={1} sx={{ py: .75 }}><Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>{item.filename} · version {item.revision}</Typography><Stack direction="row"><Button size="small" onClick={() => void viewOriginal(item.id)}>View</Button><Button size="small" onClick={() => void downloadFile(item)}>Download</Button></Stack></Stack>)}</Box>}
        </CardContent>
      </Card>

      <Card><CardContent sx={{ p: { xs: 3, md: 4 } }}><Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2}><Box><Typography variant="h6">Proposed ERP supplier record</Typography><Typography color="text.secondary" variant="body2">This is the exact payload approval will send. Only reviewed or corrected evidence overrides supplier-entered data.</Typography></Box><Button variant="outlined" size="small" disabled={erpValidating || finalized} onClick={() => void refreshErpValidation()}>{erpValidating ? 'Validating...' : 'Validate with ERP'}</Button></Stack>{erpValidationError && <Alert severity="error" sx={{ my: 2 }}>{erpValidationError} No supplier record was created; retry is safe.</Alert>}{erpValidation?.valid && <Alert severity="success" sx={{ my: 2 }}>ERP validation passed.{erpValidation.warnings.length ? ` ${erpValidation.warnings.length} optional field warning${erpValidation.warnings.length === 1 ? '' : 's'} will not block creation.` : ''}</Alert>}{erpValidation && !erpValidation.valid && <Alert severity="error" sx={{ my: 2 }}><Typography fontWeight={700}>ERP validation must be resolved before approval.</Typography>{erpValidation.errors.map((item) => <Typography key={`${item.field}-${item.code}`} variant="body2">• {item.message}</Typography>)}</Alert>}<Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'repeat(2, minmax(0, 1fr))' }, gap: 2 }}>{renderErpGroup('Identity and classification', identityErp)}{renderErpGroup('Payment, banking and risk', paymentErp)}</Box>{erpValidation?.warnings.length ? <Box sx={{ mt: 1.5 }}>{erpValidation.warnings.map((item) => <Typography key={`${item.field}-${item.code}`} variant="caption" color="text.secondary" display="block">Optional: {item.message}</Typography>)}</Box> : null}{supplier.erp_payload && <Alert severity="success" sx={{ mt: 2 }} action={<Button color="inherit" size="small" onClick={() => void openErpRecord()}>Retrieve from ERP</Button>}>The exact ERP payload was retained with this approval for audit.</Alert>}</CardContent></Card>

      <Card><CardContent sx={{ p: { xs: 3, md: 4 } }}><Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ md: 'center' }} spacing={2}><Alert severity={approvalReady ? 'success' : 'warning'} sx={{ flex: 1 }}>{approvalReady ? 'Every requirement is confirmed, policy checks pass, and ERP validation is complete.' : !complianceReady ? 'Approval stays blocked until every requirement is confirmed and all policy checks pass.' : erpValidationError ? 'Policy review is complete, but the ERP is unavailable. Retry validation safely.' : 'Policy review is complete. Resolve the ERP validation results before approval.'}</Alert><Stack direction="row" spacing={1}><Button color="error" variant="outlined" startIcon={<BlockRoundedIcon />} disabled={finalized || busy} onClick={() => setDecisionAction('reject')}>Reject</Button><Button color="success" variant="contained" startIcon={<HowToRegRoundedIcon />} disabled={!approvalReady || finalized || busy} onClick={() => setDecisionAction('approve')}>Approve and create ERP record</Button></Stack></Stack></CardContent></Card>

      <Dialog open={fieldToEdit !== null} onClose={() => !busy && setFieldToEdit(null)} fullWidth maxWidth="sm"><DialogTitle>Correct extracted value</DialogTitle><DialogContent><Stack spacing={2} sx={{ pt: 1 }}><TextField label={fieldToEdit ? fieldLabel(fieldToEdit.field_name) : 'Value'} value={editedValue} onChange={(event) => setEditedValue(event.target.value)} multiline minRows={2} autoFocus /><TextField label="Source page" type="number" value={editedPage} onChange={(event) => setEditedPage(Math.max(1, Number(event.target.value)))} slotProps={{ htmlInput: { min: 1 } }} /><Alert severity="info">The correction is recorded as a human-reviewed value and the policy checks refresh automatically.</Alert></Stack></DialogContent><DialogActions><Button onClick={() => setFieldToEdit(null)} disabled={busy}>Cancel</Button><Button variant="contained" onClick={() => void saveCorrection()} disabled={busy || !editedValue.trim()}>{busy ? 'Saving...' : 'Save correction'}</Button></DialogActions></Dialog>
      <Dialog open={flagDocumentId !== null} onClose={() => !busy && setFlagDocumentId(null)} fullWidth maxWidth="sm"><DialogTitle>Flag requirement for follow-up</DialogTitle><DialogContent><Stack spacing={2} sx={{ pt: 1 }}><DialogContentText>Explain what does not match the original evidence or policy. The reason is auditable and blocks approval.</DialogContentText><TextField label="Reason" value={flagReason} onChange={(event) => setFlagReason(event.target.value)} multiline minRows={3} autoFocus /></Stack></DialogContent><DialogActions><Button onClick={() => setFlagDocumentId(null)} disabled={busy}>Cancel</Button><Button color="error" variant="contained" onClick={() => void submitFlag()} disabled={busy || flagReason.trim().length < 5}>{busy ? 'Saving...' : 'Flag requirement'}</Button></DialogActions></Dialog>
      <Dialog open={decisionAction !== null} onClose={() => !busy && setDecisionAction(null)} fullWidth maxWidth="sm"><DialogTitle>{decisionAction === 'approve' ? 'Approve supplier and create ERP record?' : 'Reject supplier?'}</DialogTitle><DialogContent>{decisionAction === 'approve' ? <DialogContentText>This records the human decision, sends the proposed supplier record to the mock ERP, and locks the review.</DialogContentText> : <Stack spacing={2} sx={{ pt: 1 }}><DialogContentText>Provide an auditable rejection reason. No ERP record will be created.</DialogContentText><TextField label="Rejection reason" value={rejectionReason} onChange={(event) => setRejectionReason(event.target.value)} multiline minRows={3} autoFocus /></Stack>}</DialogContent><DialogActions><Button onClick={() => setDecisionAction(null)} disabled={busy}>Cancel</Button><Button color={decisionAction === 'approve' ? 'success' : 'error'} variant="contained" onClick={() => void saveDecision()} disabled={busy || (decisionAction === 'reject' && rejectionReason.trim().length < 10)}>{busy ? 'Saving decision...' : decisionAction === 'approve' ? 'Confirm approval' : 'Confirm rejection'}</Button></DialogActions></Dialog>
      <ErpRecordDialog open={showErpRecord} record={erpRecord} onClose={() => setShowErpRecord(false)} />
    </Stack>
  )
}
