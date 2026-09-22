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
import type { DocumentRevision, ExtractedField, SupplierDetail, SupplierDocument } from '../api/types'
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

const ruleLabels: Record<string, string> = {
  document_completeness: 'Required evidence',
  insurance_expiry: 'Insurance validity',
  contact_email: 'Contact email',
  supplier_name_match: 'Supplier name consistency',
  redaction_boundary: 'Sensitive-data boundary',
  field_review: 'Extracted-field review',
}

type FlagTarget = { kind: 'fields'; ids: string[] } | { kind: 'document'; id: string }

function reviewColor(status: string): 'default' | 'success' | 'warning' | 'error' {
  if (status === 'verified' || status === 'corrected') return 'success'
  if (status === 'disputed') return 'error'
  if (status === 'attention') return 'warning'
  return 'default'
}

function displayStatus(status: string) {
  return status.replaceAll('_', ' ')
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

  const loadSupplier = useCallback(async () => {
    try {
      const [detail, archived] = await Promise.all([
        api.getSupplier(supplierId),
        api.reviewerDocumentHistory(supplierId),
      ])
      setSupplier(detail)
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
      messages.push({ severity: 'warning', text: `${extracted}/${total} documents were extracted and ${indexed}/${total} were indexed. Successful work was retained.` })
      const failures = Array.isArray(latestProcessingRun.details.failed_documents)
        ? latestProcessingRun.details.failed_documents as Array<{ filename?: string; stage?: string; message?: string }> : []
      failures.forEach((failure) => messages.push({
        severity: 'error',
        text: failure.message || `${failure.stage || 'AI processing'} failed for ${failure.filename || 'a document'}.`,
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
      text: `${item.filename || 'A document'} is missing or did not expose: ${(item.fields || []).map((field) => field.replaceAll('_', ' ')).join(', ')}.`,
    }))
    const attentionDocuments = supplier.documents.filter((document) => document.review_status === 'attention' || document.review_status === 'disputed')
    if (attentionDocuments.length) messages.push({ severity: 'warning', text: `${attentionDocuments.length} evidence item(s) need attention.` })
    const attentionFields = supplier.extracted_fields.filter((field) => field.review_status === 'attention' || field.review_status === 'disputed' || field.needs_review)
    if (attentionFields.length) messages.push({ severity: 'warning', text: `${attentionFields.length} extracted field(s) need closer review.` })
    const missing = orderedEvidence.filter((item) => !item.document)
    if (missing.length) messages.push({ severity: 'error', text: `${missing.length} required evidence item(s) are missing.` })
    if (!messages.length) messages.push({ severity: 'success', text: 'No immediate document or data conflicts were detected. Human verification is still required.' })
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

  async function retryProcessing() {
    await runAction(() => api.processSupplier(supplierId), 'AI processing finished. Successful results were retained; check the summary for any remaining failures.')
  }

  async function retryDocument(document: SupplierDocument) {
    await runAction(
      () => api.processSupplierDocument(supplierId, document.id),
      `${document.filename} was processed again. Check its extraction and search-index status.`,
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
  const proposedErp = [
    ['Supplier reference', supplierReference(supplier.id)],
    ['Legal name', supplier.extracted_fields.find((field) => field.field_name === 'supplier_name')?.value ?? supplier.name],
    ['Country', supplier.country ?? '—'],
    ['Tax reference', supplier.extracted_fields.find((field) => field.field_name === 'tax_identifier')?.value ?? supplier.tax_reference ?? '—'],
    ['Contact email', supplier.extracted_fields.find((field) => field.field_name === 'contact_email')?.value ?? supplier.contact_email ?? '—'],
    ['Bank account', supplier.extracted_fields.find((field) => field.field_name === 'bank_account_number')?.value ?? supplier.bank_account_number ?? '—'],
    ['Bank IFSC', supplier.extracted_fields.find((field) => field.field_name === 'bank_ifsc')?.value ?? supplier.bank_ifsc ?? '—'],
    ['Category', `${supplier.category ?? '—'} / ${supplier.subcategory ?? '—'}`],
  ]

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
                        <Stack direction="row" spacing={0.75} alignItems="center">
                          <StatusChip status={document.processing_status} />
                          <Chip size="small" color={document.ai_extraction_status === 'ready' ? 'success' : document.ai_extraction_status === 'failed' ? 'error' : 'default'} label={`Extraction: ${displayStatus(document.ai_extraction_status)}`} />
                          <Chip size="small" color={document.ai_index_status === 'ready' ? 'success' : document.ai_index_status === 'failed' ? 'error' : 'default'} label={`Q&A index: ${displayStatus(document.ai_index_status)}`} />
                          <Chip size="small" color={reviewColor(document.review_status)} label={displayStatus(document.review_status)} />
                        </Stack>
                        {(document.ai_extraction_error || document.ai_index_error) && (
                          <Typography variant="caption" color="error" sx={{ maxWidth: 360 }}>
                            {document.ai_extraction_error || document.ai_index_error}
                          </Typography>
                        )}
                        <Stack direction="row" spacing={0.5}>
                          <Button size="small" onClick={() => void viewOriginal(document.id)}>View original</Button>
                          <Button size="small" onClick={() => void downloadFile(document)}>Download</Button>
                          {!finalized && (document.ai_extraction_status === 'failed' || document.ai_index_status === 'failed') && (
                            <Button size="small" disabled={busy} onClick={() => void retryDocument(document)}>Retry AI</Button>
                          )}
                        </Stack>
                        {!finalized && (
                          <Stack direction="row" spacing={1}>
                            <Button size="small" color="success" variant="outlined" startIcon={<CheckCircleRoundedIcon />} disabled={busy} onClick={() => void verifyEvidence(document)}>Verify</Button>
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
              <Typography variant="h6">AI review summary</Typography>
            </Stack>
            <Typography color="text.secondary" variant="body2" sx={{ mt: 0.75, mb: 2 }}>A head start for the reviewer—not an approval decision.</Typography>
            <Stack spacing={1.25}>
              {findings.map((finding, index) => <Alert key={`${finding.text}-${index}`} severity={finding.severity}>{finding.text}</Alert>)}
            </Stack>
            {latestProcessingRun && (
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 2 }}>
                Last run {new Date(latestProcessingRun.created_at).toLocaleString()} · {latestProcessingRun.model} · {(latestProcessingRun.latency_ms / 1000).toFixed(1)}s
              </Typography>
            )}
            {(!latestProcessingRun || latestProcessingRun.status === 'failed') && !finalized && (
              <Button fullWidth variant="outlined" startIcon={busy ? <CircularProgress size={17} /> : <AutoAwesomeRoundedIcon />} disabled={busy} onClick={() => void retryProcessing()} sx={{ mt: 2 }}>
                {busy ? 'Running AI review...' : 'Retry AI review'}
              </Button>
            )}
          </CardContent>
        </Card>
      </Box>

      <Card>
        <CardContent sx={{ p: { xs: 3, md: 4 } }}>
          <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2} sx={{ mb: 2.5 }}>
            <Box>
              <Typography variant="h6">AI-extracted supplier data</Typography>
              <Typography color="text.secondary" variant="body2">Select the values you have checked against the original evidence, then verify or flag them together.</Typography>
            </Box>
            {supplier.extracted_fields.length > 0 && !finalized && (
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                <Button size="small" onClick={() => setSelectedFields(allFieldsSelected ? new Set() : new Set(supplier.extracted_fields.map((field) => field.id)))}>
                  {allFieldsSelected ? 'Clear selection' : 'Select all'}
                </Button>
                <Button color="success" variant="contained" startIcon={<CheckCircleRoundedIcon />} disabled={!selectedFields.size || busy} onClick={() => void verifySelectedFields()}>Verify selected</Button>
                <Button color="error" variant="contained" startIcon={<FlagRoundedIcon />} disabled={!selectedFields.size || busy} onClick={() => setFlagTarget({ kind: 'fields', ids: [...selectedFields] })}>Flag selected</Button>
              </Stack>
            )}
          </Stack>
          {supplier.extracted_fields.length === 0 ? (
            <Alert severity="info">No supplier data has been extracted yet. Check the AI review summary.</Alert>
          ) : (
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0, 1fr))' }, gap: 2 }}>
              {supplier.extracted_fields.map((field) => {
                const source = supplier.documents.find((document) => document.id === field.document_id)
                return (
                  <Box key={field.id} sx={{ p: 2, border: 1, borderColor: field.review_status === 'disputed' ? 'error.main' : 'divider', borderRadius: 2, position: 'relative' }}>
                    <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
                      <Stack direction="row" spacing={0.75} alignItems="center">
                        {!finalized && <Checkbox size="small" checked={selectedFields.has(field.id)} onChange={() => setSelectedFields((selected) => { const next = new Set(selected); if (next.has(field.id)) next.delete(field.id); else next.add(field.id); return next })} inputProps={{ 'aria-label': `Select ${fieldLabels[field.field_name] ?? field.field_name}` }} />}
                        <Typography variant="caption" color="text.secondary" fontWeight={700}>{fieldLabels[field.field_name] ?? field.field_name}</Typography>
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
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.75 }}><FactCheckRoundedIcon color="primary" /><Typography variant="h6">Validation checks</Typography></Stack>
            <Typography color="text.secondary" variant="body2" sx={{ mb: 2 }}>Checks refresh automatically as evidence and extracted values are reviewed.</Typography>
            <Stack spacing={1.25}>
              {supplier.compliance_results.length ? supplier.compliance_results.map((result) => (
                <Box key={result.id} sx={{ p: 1.75, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                  <Stack direction="row" justifyContent="space-between" spacing={1}><Typography fontWeight={700}>{ruleLabels[result.rule_code] ?? result.rule_code}</Typography><Chip size="small" color={result.status === 'pass' ? 'success' : result.status === 'fail' ? 'error' : 'warning'} label={displayStatus(result.status)} /></Stack>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>{result.message}</Typography>
                </Box>
              )) : <Alert severity="info">Checks will appear after the AI review has run.</Alert>}
            </Stack>
          </CardContent>
        </Card>

        <Card>
          <CardContent sx={{ p: { xs: 3, md: 4 } }}>
            <Typography variant="h6">Proposed ERP supplier record</Typography>
            <Typography color="text.secondary" variant="body2" sx={{ mb: 2 }}>This is the business record that approval will create in the mock ERP. Only reviewed or corrected AI fields are sent.</Typography>
            <Stack divider={<Divider flexItem />}>
              {proposedErp.map(([label, value]) => <Stack key={label} direction="row" justifyContent="space-between" spacing={2} sx={{ py: 1 }}><Typography variant="body2" color="text.secondary">{label}</Typography><Typography variant="body2" fontWeight={650} textAlign="right" sx={{ overflowWrap: 'anywhere' }}>{String(value)}</Typography></Stack>)}
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
        <DialogContent><Stack spacing={2} sx={{ pt: 1 }}><TextField label={fieldToEdit ? fieldLabels[fieldToEdit.field_name] ?? fieldToEdit.field_name : 'Value'} value={editedValue} onChange={(event) => setEditedValue(event.target.value)} multiline minRows={2} autoFocus /><TextField label="Source page" type="number" value={editedPage} onChange={(event) => setEditedPage(Math.max(1, Number(event.target.value)))} slotProps={{ htmlInput: { min: 1 } }} /><Alert severity="info">The correction is recorded as a human-reviewed value and the checks refresh automatically.</Alert></Stack></DialogContent>
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
