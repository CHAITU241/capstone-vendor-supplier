import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded'
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded'
import BlockRoundedIcon from '@mui/icons-material/BlockRounded'
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded'
import DescriptionRoundedIcon from '@mui/icons-material/DescriptionRounded'
import EditRoundedIcon from '@mui/icons-material/EditRounded'
import FactCheckRoundedIcon from '@mui/icons-material/FactCheckRounded'
import FlagRoundedIcon from '@mui/icons-material/FlagRounded'
import HowToRegRoundedIcon from '@mui/icons-material/HowToRegRounded'
import {
  Alert,
  Box,
  Button,
  ButtonBase,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  IconButton,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { downloadOriginal, openOriginal } from '../api/openOriginal'
import { evidenceDownloadFilename, supplierReference } from '../api/supplierReference'
import type { ComplianceResult, DocumentRevision, ExtractedField, ProcessSupplierResponse, SupplierDetail, SupplierDocument } from '../api/types'
import { StatusChip } from '../components/StatusChip'

const fieldLabels: Record<string, string> = {
  supplier_name: 'Supplier name',
  address: 'Registered address',
  country: 'Country',
  tax_identifier: 'Tax reference',
  contact_name: 'Contact name',
  contact_email: 'Contact email',
  bank_account_number: 'Bank account number',
  bank_ifsc: 'Bank IFSC',
  insurance_provider: 'Insurance provider',
  insurance_expiry_date: 'Insurance expiry',
  payment_terms: 'Payment terms',
}

type FlagTarget = { kind: 'fields'; ids: string[] } | { kind: 'document'; id: string }
type PolicyGroupKey = 'matched' | 'not_matched' | 'human_review'

function reviewColor(status: string): 'default' | 'success' | 'warning' | 'error' {
  if (status === 'verified' || status === 'corrected') return 'success'
  if (status === 'disputed') return 'error'
  if (status === 'attention') return 'warning'
  return 'default'
}

function displayStatus(status: string) {
  return status.replaceAll('_', ' ')
}

function fieldLabel(fieldName: string) {
  return fieldLabels[fieldName]
    ?? fieldName.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase())
}

function failureReason(message?: string) {
  if (!message) return 'AI processing failed for one or more documents.'
  const marker = ' failed. '
  const index = message.indexOf(marker)
  return index >= 0 ? message.slice(index + marker.length) : message
}

function policyGroupFor(result: ComplianceResult): PolicyGroupKey {
  const assessment = String(result.evidence.ai_assessment)
  if (result.status === 'pass' || assessment === 'human_verified') return 'matched'
  if (result.status === 'fail' || ['not_matched', 'reviewer_flagged'].includes(assessment)) return 'not_matched'
  if (assessment === 'matched') return 'matched'
  return 'human_review'
}

const erpLabels: Record<string, string> = {
  supplier_reference: 'Supplier reference',
  legal_name: 'Legal name',
  registered_address: 'Registered address',
  country: 'Country',
  tax_reference: 'Tax reference',
  contact_name: 'Contact name',
  contact_email: 'Contact email',
  bank_account_number: 'Bank account',
  bank_ifsc: 'Bank IFSC',
  category: 'Category',
  subcategory: 'Subcategory',
  insurance_provider: 'Insurance provider',
  insurance_expiry_date: 'Insurance expiry',
  payment_terms: 'Payment terms',
}

export function SupplierReviewPage() {
  const { supplierId = '' } = useParams()
  const [supplier, setSupplier] = useState<SupplierDetail | null>(null)
  const [history, setHistory] = useState<DocumentRevision[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selectedFields, setSelectedFields] = useState<Set<string>>(new Set())
  const [fieldToEdit, setFieldToEdit] = useState<ExtractedField | null>(null)
  const [editedValue, setEditedValue] = useState('')
  const [editedPage, setEditedPage] = useState(1)
  const [flagTarget, setFlagTarget] = useState<FlagTarget | null>(null)
  const [flagReason, setFlagReason] = useState('')
  const [decisionAction, setDecisionAction] = useState<'approve' | 'reject' | null>(null)
  const [rejectionReason, setRejectionReason] = useState('')
  const [selectedPolicyGroup, setSelectedPolicyGroup] = useState<PolicyGroupKey>('not_matched')

  const loadSupplier = useCallback(async () => {
    try {
      const [detail, archived] = await Promise.all([
        api.getSupplier(supplierId),
        api.reviewerDocumentHistory(supplierId),
      ])
      setSupplier(detail)
      const policyChecks = detail.compliance_results.filter((result) => result.evidence.kind === 'policy_check')
      setSelectedPolicyGroup((current) => {
        if (policyChecks.some((result) => policyGroupFor(result) === current)) return current
        if (policyChecks.some((result) => policyGroupFor(result) === 'not_matched')) return 'not_matched'
        if (policyChecks.some((result) => policyGroupFor(result) === 'human_review')) return 'human_review'
        return 'matched'
      })
      setHistory(archived)
      setSelectedFields((selected) => new Set([...selected].filter((id) => detail.extracted_fields.some((field) => field.id === id))))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Supplier could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [supplierId])

  useEffect(() => { void loadSupplier() }, [loadSupplier])

  const orderedEvidence = useMemo(() => {
    if (!supplier) return []
    return supplier.requirements.documents.map((requirement) => ({
      requirement,
      document: supplier.documents.find((document) => document.document_type === requirement.document_type),
    }))
  }, [supplier])

  const latestProcessingRun = supplier?.ai_runs.find((run) => run.run_type === 'processing')
  const finalized = supplier?.status === 'approved' || supplier?.status === 'rejected'
  const approvalReady = Boolean(
    supplier?.compliance_results.length
    && supplier.compliance_results.every((result) => result.status === 'pass'),
  )

  const findings = useMemo(() => {
    if (!supplier) return []
    const messages: Array<{ severity: 'error' | 'warning' | 'success' | 'info'; text: string }> = []
    if (!latestProcessingRun) {
      messages.push({ severity: 'info', text: 'AI review has not run yet.' })
      return messages
    }
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
        ? latestProcessingRun.details.failed_documents as Array<{ filename?: string; stage?: string; message?: string }> : []
      const groupedFailures = new Map<string, Set<string>>()
      failures.forEach((failure) => {
        const reason = failureReason(failure.message)
        const affected = groupedFailures.get(reason) ?? new Set<string>()
        if (failure.filename) affected.add(failure.filename)
        groupedFailures.set(reason, affected)
      })
      groupedFailures.forEach((affected, reason) => messages.push({
        severity: 'error',
        text: `${reason} ${affected.size} document${affected.size === 1 ? '' : 's'} affected.`,
      }))
    }
    const mismatches = Array.isArray(latestProcessingRun.details.classification_mismatches)
      ? latestProcessingRun.details.classification_mismatches as string[] : []
    const conflicts = Array.isArray(latestProcessingRun.details.field_conflicts)
      ? latestProcessingRun.details.field_conflicts as string[] : []
    const missingFields = Array.isArray(latestProcessingRun.details.missing_required_fields)
      ? latestProcessingRun.details.missing_required_fields as Array<{ filename?: string; fields?: string[] }> : []
    if (mismatches.length) messages.push({ severity: 'warning', text: `${mismatches.length} file(s) may not match the evidence type selected by the supplier.` })
    if (conflicts.length) messages.push({ severity: 'warning', text: `Conflicting values were detected for: ${conflicts.join(', ')}.` })
    missingFields.forEach((item) => messages.push({
      severity: 'warning',
      text: `${item.filename || 'A document'} is missing or did not expose these policy fields: ${(item.fields || []).map(fieldLabel).join(', ')}.`,
    }))
    const attentionDocuments = supplier.documents.filter((document) => document.review_status === 'attention' || document.review_status === 'disputed')
    if (attentionDocuments.length) messages.push({ severity: 'warning', text: `${attentionDocuments.length} evidence item(s) need attention.` })
    const attentionFields = supplier.extracted_fields.filter((field) => field.review_status === 'attention' || field.review_status === 'disputed' || field.needs_review)
    if (attentionFields.length) messages.push({ severity: 'warning', text: `${attentionFields.length} extracted field(s) need closer review.` })
    const missing = orderedEvidence.filter((item) => !item.document)
    if (missing.length) messages.push({ severity: 'error', text: `${missing.length} required evidence item(s) are missing.` })
    if (!messages.length) messages.push({ severity: 'info', text: 'Document extraction and search indexing completed. See AI policy assessment for the policy findings.' })
    return messages
  }, [latestProcessingRun, orderedEvidence, supplier])

  async function viewOriginal(id: string) {
    try { await openOriginal(() => api.reviewerOriginal(supplierId, id)) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not open the original document.') }
  }

  async function downloadFile(document: { id: string; document_type: string; revision: number; filename: string }) {
    const requirement = supplier?.requirements.documents.find((item) => item.document_type === document.document_type)
    const filename = evidenceDownloadFilename({
      supplierId,
      documentType: document.document_type,
      revision: document.revision,
      originalFilename: document.filename,
      requirementId: requirement?.requirement_id,
      label: requirement?.label ?? document.document_type,
    })
    try { await downloadOriginal(() => api.reviewerOriginal(supplierId, document.id), filename) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not download the original document.') }
  }

  async function runAction(action: () => Promise<unknown>, success: string): Promise<boolean> {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await action()
      setNotice(success)
      await loadSupplier()
      return true
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : 'The review action could not be completed.'
      await loadSupplier()
      setError(message)
      return false
    } finally {
      setBusy(false)
    }
  }

  async function runProcessing(action: () => Promise<ProcessSupplierResponse>, success: string) {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const outcome = await action()
      await loadSupplier()
      if (outcome.failed_document_count > 0) {
        setError(`AI processing finished with ${outcome.failed_document_count} document${outcome.failed_document_count === 1 ? '' : 's'} still requiring a retry. See the consolidated AI summary.`)
        return false
      }
      setNotice(success)
      return true
    } catch (requestError) {
      await loadSupplier()
      setError(requestError instanceof Error ? requestError.message : 'AI processing could not be completed.')
      return false
    } finally {
      setBusy(false)
    }
  }

  async function runSupplierAnalysis() {
    const refresh = latestProcessingRun?.status === 'succeeded'
    await runProcessing(
      () => api.processSupplier(supplierId, refresh),
      refresh ? 'AI document analysis refreshed successfully.' : 'AI document analysis completed successfully.',
    )
  }

  async function retryDocument(document: SupplierDocument) {
    await runProcessing(
      () => api.processSupplierDocument(supplierId, document.id),
      `${document.filename} was extracted and indexed successfully.`,
    )
  }

  async function verifyEvidence(document: SupplierDocument) {
    await runAction(() => api.reviewEvidence(supplierId, document.id, 'verify'), 'Evidence marked as verified.')
  }

  async function verifySelectedFields() {
    const ids = [...selectedFields]
    if (!ids.length) return
    if (await runAction(() => api.reviewExtractedFields(supplierId, ids, 'verify'), `${ids.length} field(s) marked as verified.`)) {
      setSelectedFields(new Set())
    }
  }

  async function submitFlag() {
    if (!flagTarget || flagReason.trim().length < 5) return
    const target = flagTarget
    const saved = await runAction(
      () => target.kind === 'document'
        ? api.reviewEvidence(supplierId, target.id, 'dispute', flagReason.trim())
        : api.reviewExtractedFields(supplierId, target.ids, 'dispute', flagReason.trim()),
      'The issue was recorded and will block approval until resolved.',
    )
    if (saved) {
      setFlagTarget(null)
      setFlagReason('')
      setSelectedFields(new Set())
    }
  }

  function openFieldEditor(field: ExtractedField) {
    setFieldToEdit(field)
    setEditedValue(field.value)
    setEditedPage(field.page_number)
  }

  async function saveCorrection() {
    if (!fieldToEdit || !editedValue.trim()) return
    if (await runAction(
      () => api.updateExtractedField(supplierId, fieldToEdit.id, { value: editedValue.trim(), page_number: editedPage }),
      'Correction saved and compliance checks refreshed.',
    )) setFieldToEdit(null)
  }

  async function saveDecision() {
    if (!decisionAction) return
    const action = decisionAction
    const saved = await runAction(
      () => action === 'approve'
        ? api.approveSupplier(supplierId)
        : api.rejectSupplier(supplierId, rejectionReason.trim()),
      action === 'approve' ? 'Supplier approved and sent to the mock ERP.' : 'Supplier rejected.',
    )
    if (saved) {
      setDecisionAction(null)
      setRejectionReason('')
    }
  }

  if (loading) return <Box sx={{ display: 'grid', placeItems: 'center', py: 8 }}><CircularProgress /></Box>
  if (!supplier) return <Alert severity="error">{error || 'Supplier was not found.'}</Alert>

  const allFieldsSelected = supplier.extracted_fields.length > 0 && selectedFields.size === supplier.extracted_fields.length
  const proposedErp = Object.entries(supplier.erp_preview.payload).map(([fieldName, value]) => ({
    fieldName,
    label: erpLabels[fieldName] ?? fieldLabel(fieldName),
    value: value ?? 'Not provided',
    source: supplier.erp_preview.sources[fieldName],
  }))
  const policyChecks = supplier.compliance_results.filter((result) => result.evidence.kind === 'policy_check')
  const policyGroups = [
    {
      key: 'matched' as PolicyGroupKey,
      title: 'AI matched',
      description: 'The extracted evidence is consistent with the policy check.',
      color: 'success' as const,
      checks: policyChecks.filter((result) => policyGroupFor(result) === 'matched'),
    },
    {
      key: 'not_matched' as PolicyGroupKey,
      title: 'Not matched',
      description: 'The evidence is missing, contradicts the rule, or fails an objective threshold.',
      color: 'error' as const,
      checks: policyChecks.filter((result) => policyGroupFor(result) === 'not_matched'),
    },
    {
      key: 'human_review' as PolicyGroupKey,
      title: 'Human review',
      description: 'The evidence is ambiguous, low-confidence, or requires visual or professional judgement.',
      color: 'warning' as const,
      checks: policyChecks.filter((result) => policyGroupFor(result) === 'human_review'),
    },
  ]
  const activePolicyGroup = policyGroups.find((group) => group.key === selectedPolicyGroup) ?? policyGroups[0]
  const activePolicyRequirements = supplier.requirements.documents.map((requirement) => ({
    requirement,
    document: supplier.documents.find((document) => document.document_type === requirement.document_type),
    checks: activePolicyGroup.checks.filter((check) => check.evidence.requirement_id === requirement.requirement_id),
  })).filter((item) => item.checks.length > 0)
  const reviewControls = supplier.compliance_results.filter((result) => result.evidence.kind === 'review_control')

  return (
    <Stack spacing={3}>
      <Button component={Link} to="/review" startIcon={<ArrowBackRoundedIcon />} sx={{ alignSelf: 'flex-start' }}>Back to reviewer workspace</Button>

      <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={2}>
        <Box>
          <Typography variant="h4">{supplier.name}</Typography>
          <Chip label={`Supplier reference: ${supplierReference(supplier.id)}`} size="small" variant="outlined" sx={{ my: 0.75 }} />
          <Typography color="text.secondary">{supplier.category} / {supplier.subcategory} · {supplier.contact_email || 'No contact email'}</Typography>
        </Box>
        <StatusChip status={supplier.status} />
      </Stack>

      {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}
      {notice && <Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
      {finalized && (
        <Alert severity={supplier.status === 'approved' ? 'success' : 'error'}>
          {supplier.status === 'approved'
            ? `Approved and created in the mock ERP as ${supplier.erp_supplier_id}.`
            : `Rejected: ${supplier.decision_reason}`}
          {supplier.decided_at && ` Decision recorded ${new Date(supplier.decided_at).toLocaleString()}.`}
        </Alert>
      )}

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 2fr) minmax(320px, 1fr)' }, gap: 3, alignItems: 'start' }}>
        <Card>
          <CardContent sx={{ p: { xs: 3, md: 4 } }}>
            <Typography variant="h6">Evidence checklist</Typography>
            <Typography color="text.secondary" variant="body2" sx={{ mb: 2.5 }}>
              Evidence is arranged against the requirements for this supplier's selected service.
            </Typography>
            <Stack divider={<Divider flexItem />} spacing={0}>
              {orderedEvidence.map(({ requirement, document }) => (
                <Box key={requirement.document_type} sx={{ py: 2.25 }}>
                  <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2}>
                    <Stack direction="row" spacing={1.5} sx={{ minWidth: 0 }}>
                      <DescriptionRoundedIcon color={document ? 'primary' : 'disabled'} sx={{ mt: 0.25 }} />
                      <Box sx={{ minWidth: 0 }}>
                        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                          <Typography fontWeight={700}>{requirement.label}</Typography>
                          <Chip label={requirement.requirement_id} size="small" variant="outlined" />
                        </Stack>
                        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{requirement.accepted_evidence}</Typography>
                        {document && <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.75, overflowWrap: 'anywhere' }}>{document.filename} · {document.page_count} page(s) · version {document.revision}</Typography>}
                        {document?.review_comment && <Typography variant="caption" color={document.review_status === 'disputed' ? 'error' : 'warning.main'} display="block">{document.review_comment}</Typography>}
                      </Box>
                    </Stack>
                    {document ? (
                      <Stack spacing={1} alignItems={{ md: 'flex-end' }} sx={{ flexShrink: 0 }}>
                        <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap justifyContent={{ md: 'flex-end' }}>
                          <StatusChip status={document.processing_status} />
                          {document.ai_extraction_status === 'failed' && document.ai_index_status === 'failed' ? (
                            <Tooltip title="See document processing for the root cause.">
                              <Chip size="small" color="error" label="AI unavailable" />
                            </Tooltip>
                          ) : (
                            <>
                              <Chip size="small" color={document.ai_extraction_status === 'ready' ? 'success' : document.ai_extraction_status === 'failed' ? 'error' : 'default'} label={`Extraction: ${displayStatus(document.ai_extraction_status)}`} />
                              <Chip size="small" color={document.ai_index_status === 'ready' ? 'success' : document.ai_index_status === 'failed' ? 'error' : 'default'} label={`Q&A index: ${displayStatus(document.ai_index_status)}`} />
                            </>
                          )}
                          <Chip size="small" color={reviewColor(document.review_status)} label={displayStatus(document.review_status)} />
                        </Stack>
                        <Stack direction="row" spacing={0.5}>
                          <Button size="small" onClick={() => void viewOriginal(document.id)}>View original</Button>
                          <Button size="small" onClick={() => void downloadFile(document)}>Download</Button>
                          {!finalized && (document.ai_extraction_status === 'failed' || document.ai_index_status === 'failed') && (
                            <Button size="small" disabled={busy} onClick={() => void retryDocument(document)}>Retry AI</Button>
                          )}
                        </Stack>
                        {!finalized && (
                          <Stack direction="row" spacing={1}>
                            <Button size="small" color="success" variant="outlined" startIcon={<CheckCircleRoundedIcon />} disabled={busy} onClick={() => void verifyEvidence(document)}>Verify checks</Button>
                            <Button size="small" color="error" variant="outlined" startIcon={<FlagRoundedIcon />} disabled={busy} onClick={() => setFlagTarget({ kind: 'document', id: document.id })}>Flag</Button>
                          </Stack>
                        )}
                      </Stack>
                    ) : <Chip label="Missing" size="small" color="error" />}
                  </Stack>
                </Box>
              ))}
            </Stack>
            {history.length > 0 && (
              <Box sx={{ mt: 2, pt: 2, borderTop: 1, borderColor: 'divider' }}>
                <Typography fontWeight={700}>Previous versions</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Retained originals remain available for audit.</Typography>
                {history.map((item) => (
                  <Stack key={item.id} direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={1} sx={{ py: 0.75 }}>
                    <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>{item.filename} · version {item.revision}</Typography>
                    <Stack direction="row"><Button size="small" onClick={() => void viewOriginal(item.id)}>View</Button><Button size="small" onClick={() => void downloadFile(item)}>Download</Button></Stack>
                  </Stack>
                ))}
              </Box>
            )}
          </CardContent>
        </Card>

        <Card sx={{ position: { lg: 'sticky' }, top: { lg: 88 } }}>
          <CardContent sx={{ p: 3 }}>
            <Stack direction="row" spacing={1} alignItems="center">
              <AutoAwesomeRoundedIcon color="primary" />
              <Typography variant="h6">Document processing</Typography>
            </Stack>
            <Typography color="text.secondary" variant="body2" sx={{ mt: 0.75, mb: 2 }}>Extraction, indexing, and technical issues. Policy findings are shown in the assessment below.</Typography>
            <Stack spacing={1.25}>
              {findings.map((finding, index) => (
                <Alert key={`${finding.text}-${index}`} severity={finding.severity} sx={{ overflowWrap: 'anywhere', '& .MuiAlert-message': { minWidth: 0 } }}>
                  {finding.text}
                </Alert>
              ))}
            </Stack>
            {latestProcessingRun && (
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 2 }}>
                Last run {new Date(latestProcessingRun.created_at).toLocaleString()} · {latestProcessingRun.model} · {(latestProcessingRun.latency_ms / 1000).toFixed(1)}s
              </Typography>
            )}
            {!finalized && (
              <Button fullWidth variant="outlined" startIcon={busy ? <CircularProgress size={17} /> : <AutoAwesomeRoundedIcon />} disabled={busy} onClick={() => void runSupplierAnalysis()} sx={{ mt: 2 }}>
                {busy
                  ? 'Analyzing documents...'
                  : !latestProcessingRun
                    ? 'Run AI document analysis'
                    : latestProcessingRun.status === 'failed'
                      ? 'Retry failed analysis'
                      : 'Refresh AI analysis'}
              </Button>
            )}
          </CardContent>
        </Card>
      </Box>

      <Card>
        <CardContent sx={{ p: { xs: 3, md: 4 } }}>
          <Box sx={{ mb: 2.5 }}>
            <Typography variant="h6">AI-extracted supplier data</Typography>
            <Typography color="text.secondary" variant="body2">Select the values you have checked against the original evidence, then verify or flag them together.</Typography>
            {supplier.extracted_fields.length > 0 && !finalized && (
              <Stack direction="row" spacing={1} alignItems="center" justifyContent="flex-end" flexWrap={{ xs: 'wrap', sm: 'nowrap' }} useFlexGap sx={{ mt: 2, minHeight: 40 }}>
                <Button size="small" sx={{ minWidth: 112 }} onClick={() => setSelectedFields(allFieldsSelected ? new Set() : new Set(supplier.extracted_fields.map((field) => field.id)))}>
                  {allFieldsSelected ? 'Clear selection' : 'Select all'}
                </Button>
                <Button color="success" variant="contained" startIcon={<CheckCircleRoundedIcon />} disabled={!selectedFields.size || busy} onClick={() => void verifySelectedFields()}>Verify selected</Button>
                <Button color="error" variant="contained" startIcon={<FlagRoundedIcon />} disabled={!selectedFields.size || busy} onClick={() => setFlagTarget({ kind: 'fields', ids: [...selectedFields] })}>Flag selected</Button>
              </Stack>
            )}
          </Box>
          {supplier.extracted_fields.length === 0 ? (
            <Alert severity="info">No supplier data has been extracted yet. Check document processing.</Alert>
          ) : (
            <Box sx={{ maxHeight: { xs: 'none', md: 'calc(100vh - 260px)' }, minHeight: { md: 280 }, overflowY: { xs: 'visible', md: 'auto' }, pr: { md: 1 }, scrollbarGutter: 'stable', display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0, 1fr))' }, gap: 2, alignContent: 'start' }}>
              {supplier.extracted_fields.map((field) => {
                const source = supplier.documents.find((document) => document.id === field.document_id)
                return (
                  <Box key={field.id} sx={{ p: 2, border: 1, borderColor: field.review_status === 'disputed' ? 'error.main' : 'divider', borderRadius: 2, position: 'relative' }}>
                    <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
                      <Stack direction="row" spacing={0.75} alignItems="center">
                        {!finalized && <Checkbox size="small" checked={selectedFields.has(field.id)} onChange={() => setSelectedFields((selected) => { const next = new Set(selected); if (next.has(field.id)) next.delete(field.id); else next.add(field.id); return next })} inputProps={{ 'aria-label': `Select ${fieldLabel(field.field_name)}` }} />}
                        <Typography variant="caption" color="text.secondary" fontWeight={700}>{fieldLabel(field.field_name)}</Typography>
                      </Stack>
                      <Stack direction="row" spacing={0.5} alignItems="center">
                        <Chip size="small" color={reviewColor(field.review_status)} label={displayStatus(field.review_status)} />
                        {!finalized && <Tooltip title="Correct value"><IconButton size="small" onClick={() => openFieldEditor(field)}><EditRoundedIcon fontSize="small" /></IconButton></Tooltip>}
                      </Stack>
                    </Stack>
                    <Typography fontWeight={650} sx={{ my: 1, overflowWrap: 'anywhere' }}>{field.value}</Typography>
                    <Typography variant="caption" color="text.secondary">{source?.filename ?? 'Source document'} · page {field.page_number} · {Math.round(field.confidence * 100)}% AI confidence</Typography>
                    {field.review_comment && <Alert severity={field.review_status === 'disputed' ? 'error' : 'info'} sx={{ mt: 1.25, py: 0 }}>{field.review_comment}</Alert>}
                  </Box>
                )
              })}
            </Box>
          )}
        </CardContent>
      </Card>

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1fr) minmax(0, 1fr)' }, gap: 3 }}>
        <Card>
          <CardContent sx={{ p: { xs: 3, md: 4 } }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.75 }}><FactCheckRoundedIcon color="primary" /><Typography variant="h6">AI policy assessment</Typography></Stack>
            <Typography color="text.secondary" variant="body2">A provisional comparison of the uploaded evidence against every applicable numbered policy check. The reviewer remains the decision-maker.</Typography>
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(3, 1fr)' }, gap: 1, my: 2 }}>
              {policyGroups.map((group) => (
                <ButtonBase
                  key={group.key}
                  aria-pressed={selectedPolicyGroup === group.key}
                  onClick={() => setSelectedPolicyGroup(group.key)}
                  sx={{ p: 1.5, border: 1, borderColor: `${group.color}.main`, borderRadius: 2, bgcolor: selectedPolicyGroup === group.key ? 'action.selected' : 'action.hover', display: 'block', textAlign: 'left', width: '100%', transition: 'box-shadow 120ms ease', boxShadow: selectedPolicyGroup === group.key ? 2 : 0, '&:hover': { bgcolor: 'action.selected' } }}
                >
                  <Typography variant="h5" color={`${group.color}.dark`} fontWeight={750}>{group.checks.length}</Typography>
                  <Typography variant="body2" fontWeight={700}>{group.title}</Typography>
                </ButtonBase>
              ))}
            </Box>
            <Stack spacing={1.5}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
                <Box>
                  <Typography fontWeight={750}>{activePolicyGroup.title}</Typography>
                  <Typography variant="caption" color="text.secondary">{activePolicyGroup.description}</Typography>
                </Box>
                <Chip size="small" color={activePolicyGroup.color} label={activePolicyGroup.checks.length} />
              </Stack>
              {activePolicyRequirements.length === 0 ? (
                <Alert severity="info">No checks in this group.</Alert>
              ) : activePolicyRequirements.map(({ requirement, document, checks }) => (
                <Box key={requirement.requirement_id} sx={{ border: 1, borderColor: 'divider', borderRadius: 2, overflow: 'hidden' }}>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={1} sx={{ px: 1.75, py: 1.25, bgcolor: 'action.hover' }}>
                    <Box>
                      <Typography variant="body2" fontWeight={750}>{requirement.label}</Typography>
                      <Typography variant="caption" color="text.secondary">{requirement.requirement_id} · {checks.length} check{checks.length === 1 ? '' : 's'}</Typography>
                    </Box>
                    {document && <Button size="small" startIcon={<DescriptionRoundedIcon />} onClick={() => void viewOriginal(document.id)}>View document</Button>}
                  </Stack>
                  <Stack divider={<Divider flexItem />}>
                    {checks.map((check) => {
                      const observed = Array.isArray(check.evidence.observed_values)
                        ? check.evidence.observed_values as Array<{ field_name?: string; value?: unknown; page_number?: number }>
                        : []
                      const expected = Array.isArray(check.evidence.expected_values)
                        ? check.evidence.expected_values as Array<{ field_name?: string; value?: unknown; source?: string }>
                        : []
                      const reason = String(check.evidence.ai_reason ?? check.message)
                      return (
                        <Box key={check.id} sx={{ px: 1.75, py: 1.5 }}>
                          <Stack direction="row" justifyContent="space-between" spacing={1} alignItems="flex-start">
                            <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>{reason}</Typography>
                            <Typography variant="caption" color="text.secondary" sx={{ flexShrink: 0 }}>Check {String(check.evidence.check_number)}</Typography>
                          </Stack>
                          {selectedPolicyGroup !== 'matched' && (
                            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 1, mt: 1.25 }}>
                              <Box sx={{ p: 1.25, borderRadius: 1.5, bgcolor: 'rgba(211, 47, 47, 0.06)' }}>
                                <Typography variant="caption" fontWeight={750} color="error.dark">Observed</Typography>
                                {observed.length ? observed.map((item, index) => (
                                  <Typography key={`${item.field_name}-${index}`} variant="caption" display="block" sx={{ mt: 0.4, overflowWrap: 'anywhere' }}>
                                    {fieldLabel(String(item.field_name ?? 'value'))}: {item.value == null || item.value === '' ? 'Not found' : String(item.value)}{item.page_number ? ` · page ${item.page_number}` : ''}
                                  </Typography>
                                )) : <Typography variant="caption" display="block" sx={{ mt: 0.4 }}>No reliable value was extracted.</Typography>}
                              </Box>
                              <Box sx={{ p: 1.25, borderRadius: 1.5, bgcolor: 'action.hover' }}>
                                <Typography variant="caption" fontWeight={750}>Expected</Typography>
                                {expected.map((item, index) => (
                                  <Typography key={`${item.field_name}-${index}`} variant="caption" display="block" sx={{ mt: 0.4, overflowWrap: 'anywhere' }}>
                                    {item.field_name === 'policy_rule' ? '' : `${fieldLabel(String(item.field_name ?? 'value'))}: `}{String(item.value ?? 'Not specified')}
                                  </Typography>
                                ))}
                              </Box>
                            </Box>
                          )}
                          {check.status === 'pass' && <Chip size="small" color="success" label="Reviewer verified" sx={{ mt: 1 }} />}
                        </Box>
                      )
                    })}
                  </Stack>
                </Box>
              ))}
              {reviewControls.map((result) => (
                <Alert key={result.id} severity={result.status === 'pass' ? 'success' : result.status === 'fail' ? 'error' : 'warning'}>
                  <Typography variant="body2" fontWeight={700}>Extracted-value review</Typography>
                  <Typography variant="body2">{result.message}</Typography>
                </Alert>
              ))}
            </Stack>
          </CardContent>
        </Card>

        <Card>
          <CardContent sx={{ p: { xs: 3, md: 4 } }}>
            <Typography variant="h6">Proposed ERP supplier record</Typography>
            <Typography color="text.secondary" variant="body2" sx={{ mb: 2 }}>This is the exact payload approval will send. Pending AI values are excluded; reviewed evidence overrides supplier-entered data.</Typography>
            <Stack divider={<Divider flexItem />}>
              {proposedErp.map((item) => (
                <Stack key={item.fieldName} direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1.5} sx={{ py: 1 }}>
                  <Typography variant="body2" color="text.secondary">{item.label}</Typography>
                  <Stack alignItems={{ sm: 'flex-end' }} spacing={0.5} sx={{ minWidth: 0 }}>
                    <Typography variant="body2" fontWeight={650} textAlign={{ sm: 'right' }} sx={{ overflowWrap: 'anywhere' }}>{String(item.value)}</Typography>
                    <Chip
                      size="small"
                      variant="outlined"
                      color={item.source?.source === 'reviewed_evidence' ? 'success' : item.source?.source === 'supplier_entered' ? 'info' : item.source?.source === 'not_available' ? 'warning' : 'default'}
                      label={item.source?.label ?? 'Unknown source'}
                    />
                  </Stack>
                </Stack>
              ))}
            </Stack>
            {supplier.erp_payload && <Alert severity="success" sx={{ mt: 2 }}>The exact ERP payload was retained with this approval for audit.</Alert>}
          </CardContent>
        </Card>
      </Box>

      <Card>
        <CardContent sx={{ p: { xs: 3, md: 4 } }}>
          <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ md: 'center' }} spacing={2}>
            <Alert severity={approvalReady ? 'success' : 'warning'} sx={{ flex: 1 }}>
              {approvalReady ? 'Evidence, extracted values, and validation checks are complete. Approval is enabled.' : 'Approval stays blocked until every required evidence item and extracted field is reviewed and all checks pass.'}
            </Alert>
            <Stack direction="row" spacing={1}>
              <Button color="error" variant="outlined" startIcon={<BlockRoundedIcon />} disabled={finalized || busy} onClick={() => setDecisionAction('reject')}>Reject</Button>
              <Button color="success" variant="contained" startIcon={<HowToRegRoundedIcon />} disabled={!approvalReady || finalized || busy} onClick={() => setDecisionAction('approve')}>Approve and send to ERP</Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      <Dialog open={fieldToEdit !== null} onClose={() => !busy && setFieldToEdit(null)} fullWidth maxWidth="sm">
        <DialogTitle>Correct extracted value</DialogTitle>
        <DialogContent><Stack spacing={2} sx={{ pt: 1 }}><TextField label={fieldToEdit ? fieldLabel(fieldToEdit.field_name) : 'Value'} value={editedValue} onChange={(event) => setEditedValue(event.target.value)} multiline minRows={2} autoFocus /><TextField label="Source page" type="number" value={editedPage} onChange={(event) => setEditedPage(Math.max(1, Number(event.target.value)))} slotProps={{ htmlInput: { min: 1 } }} /><Alert severity="info">The correction is recorded as a human-reviewed value and the checks refresh automatically.</Alert></Stack></DialogContent>
        <DialogActions><Button onClick={() => setFieldToEdit(null)} disabled={busy}>Cancel</Button><Button variant="contained" onClick={() => void saveCorrection()} disabled={busy || !editedValue.trim()}>{busy ? 'Saving...' : 'Save correction'}</Button></DialogActions>
      </Dialog>

      <Dialog open={flagTarget !== null} onClose={() => !busy && setFlagTarget(null)} fullWidth maxWidth="sm">
        <DialogTitle>Flag for follow-up</DialogTitle>
        <DialogContent><Stack spacing={2} sx={{ pt: 1 }}><DialogContentText>Explain what does not match the original evidence. This creates an auditable issue and blocks approval.</DialogContentText><TextField label="Issue" value={flagReason} onChange={(event) => setFlagReason(event.target.value)} multiline minRows={3} autoFocus /></Stack></DialogContent>
        <DialogActions><Button onClick={() => setFlagTarget(null)} disabled={busy}>Cancel</Button><Button color="error" variant="contained" onClick={() => void submitFlag()} disabled={busy || flagReason.trim().length < 5}>{busy ? 'Saving...' : 'Flag item'}</Button></DialogActions>
      </Dialog>

      <Dialog open={decisionAction !== null} onClose={() => !busy && setDecisionAction(null)} fullWidth maxWidth="sm">
        <DialogTitle>{decisionAction === 'approve' ? 'Approve supplier and create ERP record?' : 'Reject supplier?'}</DialogTitle>
        <DialogContent>
          {decisionAction === 'approve'
            ? <DialogContentText>This records the human decision, sends the proposed supplier record to the mock ERP, and locks the review.</DialogContentText>
            : <Stack spacing={2} sx={{ pt: 1 }}><DialogContentText>Provide an auditable rejection reason. No ERP record will be created.</DialogContentText><TextField label="Rejection reason" value={rejectionReason} onChange={(event) => setRejectionReason(event.target.value)} multiline minRows={3} autoFocus /></Stack>}
        </DialogContent>
        <DialogActions><Button onClick={() => setDecisionAction(null)} disabled={busy}>Cancel</Button><Button color={decisionAction === 'approve' ? 'success' : 'error'} variant="contained" onClick={() => void saveDecision()} disabled={busy || (decisionAction === 'reject' && rejectionReason.trim().length < 10)}>{busy ? 'Saving decision...' : decisionAction === 'approve' ? 'Confirm approval' : 'Confirm rejection'}</Button></DialogActions>
      </Dialog>
    </Stack>
  )
}
