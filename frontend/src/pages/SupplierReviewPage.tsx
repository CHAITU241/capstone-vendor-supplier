import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded'
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded'
import CloudUploadRoundedIcon from '@mui/icons-material/CloudUploadRounded'
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import DescriptionRoundedIcon from '@mui/icons-material/DescriptionRounded'
import EditRoundedIcon from '@mui/icons-material/EditRounded'
import FactCheckRoundedIcon from '@mui/icons-material/FactCheckRounded'
import HowToRegRoundedIcon from '@mui/icons-material/HowToRegRounded'
import BlockRoundedIcon from '@mui/icons-material/BlockRounded'
import QuestionAnswerRoundedIcon from '@mui/icons-material/QuestionAnswerRounded'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { ChangeEvent, useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { downloadOriginal, openOriginal } from '../api/openOriginal'
import type {
  DocumentRevision,
  DocumentType,
  ExtractedField,
  SupplierDetail,
  SupplierDocument,
  SupplierQuestionResponse,
} from '../api/types'
import { StatusChip } from '../components/StatusChip'

const documentLabels: Record<DocumentType, string> = {
  registration: 'Supplier registration form',
  tax: 'Tax registration certificate',
  insurance: 'Insurance certificate',
}

const fieldLabels: Record<string, string> = {
  supplier_name: 'Supplier name',
  address: 'Registered address',
  country: 'Country',
  tax_identifier: 'Tax ID',
  contact_name: 'Contact name',
  contact_email: 'Contact email',
  insurance_provider: 'Insurance provider',
  insurance_expiry_date: 'Insurance expiry',
  payment_terms: 'Payment terms',
}

const ruleLabels: Record<string, string> = {
  document_completeness: 'Required documents',
  insurance_expiry: 'Insurance validity',
  contact_email: 'Contact email',
  supplier_name_match: 'Supplier name match',
  redaction_boundary: 'PII redaction boundary',
  field_review: 'Human field review',
}

type FieldConflictDetail = {
  field_name: string
  selected_document: string | null
  source_documents: (string | null)[]
  source_document_types: string[]
}

export function SupplierReviewPage() {
  const { supplierId = '' } = useParams()
  const [supplier, setSupplier] = useState<SupplierDetail | null>(null)
  const [history, setHistory] = useState<DocumentRevision[]>([])
  const [documentType, setDocumentType] = useState<DocumentType>('registration')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [documentToDelete, setDocumentToDelete] = useState<SupplierDocument | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [questionResponse, setQuestionResponse] = useState<SupplierQuestionResponse | null>(null)
  const [checkingCompliance, setCheckingCompliance] = useState(false)
  const [fieldToEdit, setFieldToEdit] = useState<ExtractedField | null>(null)
  const [editedValue, setEditedValue] = useState('')
  const [editedPage, setEditedPage] = useState(1)
  const [savingField, setSavingField] = useState(false)
  const [decisionAction, setDecisionAction] = useState<'approve' | 'reject' | null>(null)
  const [rejectionReason, setRejectionReason] = useState('')
  const [deciding, setDeciding] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const requiredDocuments = supplier?.requirements.documents ?? []
  const availableDocumentTypes = requiredDocuments
    .filter((item) => !supplier?.documents.some((document) => document.document_type === item.document_type))
    .map((item) => [item.document_type, item.label] as [DocumentType, string])
  const effectiveDocumentType = availableDocumentTypes.some(([value]) => value === documentType)
    ? documentType
    : availableDocumentTypes[0]?.[0]
  const allDocumentsReady = requiredDocuments.length > 0
    && requiredDocuments.every((item) => supplier?.documents.some((document) => document.document_type === item.document_type && document.processing_status === 'ready'))
  const latestProcessingRun = supplier?.ai_runs.find((run) => run.run_type === 'processing')
  const finalized = supplier?.status === 'approved' || supplier?.status === 'rejected'
  const approvalReady = Boolean(supplier && supplier.compliance_results.length >= Object.keys(ruleLabels).length
    && supplier.compliance_results.every((result) => result.status === 'pass')
  )

  function fieldReviewMessage(field: ExtractedField, sourceDocument: SupplierDocument | undefined): string {
    const conflictDetails = Array.isArray(latestProcessingRun?.details.field_conflict_details)
      ? latestProcessingRun.details.field_conflict_details as FieldConflictDetail[]
      : []
    const conflict = conflictDetails.find((item) => item.field_name === field.field_name)
    const mismatchFiles = Array.isArray(latestProcessingRun?.details.classification_mismatches)
      ? latestProcessingRun.details.classification_mismatches as string[]
      : []
    const reasons: string[] = []

    if (conflict) {
      const sources = conflict.source_documents.filter((filename): filename is string => Boolean(filename))
      const otherSources = sources.filter((filename) => filename !== conflict.selected_document)
      const sourceText = otherSources.length > 0 ? ` Another value was found in ${otherSources.join(', ')}.` : ''
      reasons.push(
        `Conflicting values were found across the uploaded documents. The displayed value was selected from ${conflict.selected_document ?? 'the highest-priority source'} based on document priority.${sourceText}`,
      )
    }
    if (field.confidence < 0.75) {
      reasons.push(`AI confidence is ${Math.round(field.confidence * 100)}%, below the 75% review threshold.`)
    }
    if (sourceDocument && mismatchFiles.includes(sourceDocument.filename)) {
      reasons.push('The source document category did not match the category selected during upload.')
    }
    if (reasons.length === 0) {
      reasons.push('The AI could not confirm this value with sufficient certainty from the source document.')
    }

    return `${reasons.join(' ')} Confirm the value against page ${field.page_number} before approval.`
  }

  const loadSupplier = useCallback(async () => {
    try {
      const [detail, archived] = await Promise.all([api.getSupplier(supplierId), api.reviewerDocumentHistory(supplierId)])
      setSupplier(detail)
      setHistory(archived)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Supplier could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [supplierId])

  useEffect(() => { void loadSupplier() }, [loadSupplier])

  async function viewOriginal(id: string) {
    try { await openOriginal(() => api.reviewerOriginal(supplierId, id)) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not open the original document.') }
  }

  async function downloadFile(id: string, filename: string) {
    try { await downloadOriginal(() => api.reviewerOriginal(supplierId, id), filename) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not download the original document.') }
  }

  async function handleUpload() {
    if (!selectedFile || !effectiveDocumentType) return
    setUploading(true)
    setError('')
    setNotice('')
    try {
      await api.uploadDocument(supplierId, effectiveDocumentType, selectedFile)
      setSelectedFile(null)
      await loadSupplier()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Document upload failed.')
    } finally {
      setUploading(false)
    }
  }

  async function handleDelete() {
    if (!documentToDelete) return
    setDeleting(true)
    setError('')
    setNotice('')
    try {
      await api.deleteDocument(supplierId, documentToDelete.id)
      setSelectedFile(null)
      setDocumentToDelete(null)
      setQuestionResponse(null)
      await loadSupplier()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Document deletion failed.')
    } finally {
      setDeleting(false)
    }
  }

  async function handleProcess() {
    setProcessing(true)
    setError('')
    setNotice('')
    setQuestionResponse(null)
    try {
      const result = await api.processSupplier(supplierId)
      setNotice(`Processing complete: ${result.field_count} fields extracted and ${result.chunk_count} searchable chunks created.`)
      await loadSupplier()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Document processing failed.')
      await loadSupplier()
    } finally {
      setProcessing(false)
    }
  }

  async function handleAskQuestion() {
    const trimmedQuestion = question.trim()
    if (trimmedQuestion.length < 3) return
    setAsking(true)
    setError('')
    setNotice('')
    try {
      const result = await api.askSupplierQuestion(supplierId, trimmedQuestion)
      setQuestionResponse(result)
      await loadSupplier()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'The question could not be answered.')
    } finally {
      setAsking(false)
    }
  }

  function openFieldEditor(field: ExtractedField) {
    setFieldToEdit(field)
    setEditedValue(field.value)
    setEditedPage(field.page_number)
  }

  async function handleSaveField() {
    if (!fieldToEdit || !editedValue.trim()) return
    setSavingField(true)
    setError('')
    setNotice('')
    try {
      await api.updateExtractedField(supplierId, fieldToEdit.id, {
        value: editedValue.trim(),
        page_number: editedPage,
      })
      setFieldToEdit(null)
      setNotice('Field correction saved. Run compliance checks again before approval.')
      await loadSupplier()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Field correction failed.')
    } finally {
      setSavingField(false)
    }
  }

  async function handleRunCompliance() {
    setCheckingCompliance(true)
    setError('')
    setNotice('')
    try {
      const result = await api.runCompliance(supplierId)
      setNotice(result.approval_ready ? 'All compliance checks passed. The supplier is ready for approval.' : 'Compliance checks completed. Resolve the highlighted issues before approval.')
      await loadSupplier()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Compliance checks failed.')
    } finally {
      setCheckingCompliance(false)
    }
  }

  async function handleDecision() {
    if (!decisionAction) return
    setDeciding(true)
    setError('')
    setNotice('')
    try {
      const result = decisionAction === 'approve'
        ? await api.approveSupplier(supplierId)
        : await api.rejectSupplier(supplierId, rejectionReason.trim())
      setDecisionAction(null)
      setRejectionReason('')
      setNotice(result.message)
      await loadSupplier()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'The decision could not be completed.')
    } finally {
      setDeciding(false)
    }
  }

  if (loading) return <Box sx={{ display: 'grid', placeItems: 'center', py: 8 }}><CircularProgress /></Box>
  if (!supplier) return <Alert severity="error">{error || 'Supplier was not found.'}</Alert>

  return (
    <Stack spacing={3}>
      <Button component={Link} to="/review" startIcon={<ArrowBackRoundedIcon />} sx={{ alignSelf: 'flex-start' }}>Back to reviewer workspace</Button>
      <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={2}>
        <Box>
          <Typography variant="h4">{supplier.name}</Typography>
          <Typography color="text.secondary">{supplier.category ? `${supplier.category} / ${supplier.subcategory} · ` : ''}{supplier.country || 'Country not provided'} / {supplier.contact_email || 'No contact email'}</Typography>
        </Box>
        <StatusChip status={supplier.status} />
      </Stack>
      {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}
      {notice && <Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
      <Alert severity="info">Checklist {supplier.requirements.version}: {supplier.requirements.reason}{supplier.requirements.status === 'synthetic_demo_policy' && ' Uploaded files require human verification against the numbered evidence checks; automated approval is blocked.'}</Alert>
      {finalized && (
        <Alert severity={supplier.status === 'approved' ? 'success' : 'error'}>
          {supplier.status === 'approved'
            ? `Approved and created in the mock ERP as ${supplier.erp_supplier_id}.`
            : `Rejected: ${supplier.decision_reason}`}
          {supplier.decided_at && ` Decision recorded ${new Date(supplier.decided_at).toLocaleString()}.`}
        </Alert>
      )}

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 2fr) minmax(300px, 1fr)' }, gap: 3 }}>
        <Card><CardContent sx={{ p: { xs: 3, md: 4 } }}>
          <Typography variant="h6">Documents</Typography>
          <Typography color="text.secondary" variant="body2" sx={{ mb: 3 }}>PDF or UTF-8 text, up to 10 MB each.</Typography>
          {supplier.documents.length === 0 ? (
            <Alert severity="info">No documents uploaded yet.</Alert>
          ) : (
            <Stack divider={<Divider flexItem />} spacing={0}>
              {supplier.documents.map((document) => (
                <Stack key={document.id} direction="row" justifyContent="space-between" alignItems="center" spacing={2} sx={{ py: 2 }}>
                  <Stack direction="row" spacing={1.5} alignItems="center" sx={{ minWidth: 0 }}>
                    <DescriptionRoundedIcon color="primary" />
                    <Box sx={{ minWidth: 0 }}>
                      <Typography noWrap fontWeight={650}>{document.filename}</Typography>
                      <Typography variant="caption" color="text.secondary">{requiredDocuments.find((item) => item.document_type === document.document_type)?.label ?? documentLabels[document.document_type] ?? document.document_type} / {document.page_count} page(s)</Typography>
                      {document.error_message && <Typography variant="caption" color="error" display="block">{document.error_message}</Typography>}
                    </Box>
                  </Stack>
                  <Stack direction="row" alignItems="center" spacing={0.5}>
                    <StatusChip status={document.processing_status} />
                    <Button size="small" onClick={() => void viewOriginal(document.id)}>View original</Button>
                    <Button size="small" onClick={() => void downloadFile(document.id, document.filename)}>Download</Button>
                    <Tooltip title="Delete document">
                      <IconButton
                        aria-label={`Delete ${document.filename}`}
                        color="error"
                        disabled={finalized}
                        onClick={() => setDocumentToDelete(document)}
                      >
                        <DeleteOutlineRoundedIcon />
                      </IconButton>
                    </Tooltip>
                  </Stack>
                </Stack>
              ))}
            </Stack>
          )}
          {history.length > 0 && <Box sx={{ mt: 3 }}>
            <Typography fontWeight={700}>Previous uploads</Typography>
            <Typography variant="body2" color="text.secondary">Retained originals from earlier uploads.</Typography>
            {history.map((item) => <Stack key={item.id} direction="row" justifyContent="space-between" alignItems="center" spacing={1} sx={{ py: 1 }}>
              <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>{item.filename} · version {item.revision}</Typography>
              <Button size="small" onClick={() => void viewOriginal(item.id)}>View original</Button>
              <Button size="small" onClick={() => void downloadFile(item.id, item.filename)}>Download</Button>
            </Stack>)}
          </Box>}
        </CardContent></Card>

        <Card><CardContent sx={{ p: 3 }}>
          <Stack spacing={2.5}>
            <Typography variant="h6">Upload document</Typography>
            {finalized ? (
              <Alert severity="info">Documents are locked after a final decision.</Alert>
            ) : effectiveDocumentType ? (
              <>
                <TextField select label="Document type" value={effectiveDocumentType} onChange={(event) => setDocumentType(event.target.value as DocumentType)}>
                  {availableDocumentTypes.map(([value, label]) => <MenuItem key={value} value={value}>{label}</MenuItem>)}
                </TextField>
                <Button component="label" variant="outlined" startIcon={<CloudUploadRoundedIcon />}>
                  {selectedFile ? 'Change file' : 'Choose file'}
                  <input hidden type="file" accept="application/pdf,text/plain,.pdf,.txt" onChange={(event: ChangeEvent<HTMLInputElement>) => setSelectedFile(event.target.files?.[0] ?? null)} />
                </Button>
                {selectedFile && <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>{selectedFile.name}</Typography>}
                <Button variant="contained" disabled={!selectedFile || uploading} onClick={handleUpload}>
                  {uploading ? 'Uploading and extracting...' : 'Upload document'}
                </Button>
              </>
            ) : (
              <Alert severity="success">All requested document types have been uploaded.</Alert>
            )}
          </Stack>
        </CardContent></Card>
      </Box>

      <Card><CardContent sx={{ p: { xs: 3, md: 4 } }}>
        <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ md: 'center' }} spacing={2}>
          <Box>
            <Stack direction="row" spacing={1} alignItems="center">
              <AutoAwesomeRoundedIcon color="primary" />
              <Typography variant="h6">AI document processing</Typography>
            </Stack>
            <Typography color="text.secondary" variant="body2" sx={{ mt: 0.75 }}>
              Redact sensitive data, extract review fields, and build the supplier-scoped search index.
            </Typography>
            {latestProcessingRun && (
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                Last run: {latestProcessingRun.model} / {latestProcessingRun.input_tokens + latestProcessingRun.output_tokens} tokens / {(latestProcessingRun.latency_ms / 1000).toFixed(1)}s / {latestProcessingRun.status}
              </Typography>
            )}
          </Box>
          <Button
            variant="contained"
            startIcon={processing ? <CircularProgress size={18} color="inherit" /> : <AutoAwesomeRoundedIcon />}
            disabled={!allDocumentsReady || processing || finalized}
            onClick={handleProcess}
          >
            {processing ? 'Processing documents...' : supplier.extracted_fields.length ? 'Reprocess documents' : 'Process documents'}
          </Button>
        </Stack>
        {!allDocumentsReady && <Alert severity="info" sx={{ mt: 2 }}>All documents in this application's checklist must be ready before processing.</Alert>}
      </CardContent></Card>

      <Card><CardContent sx={{ p: { xs: 3, md: 4 } }}>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.75 }}>
          <QuestionAnswerRoundedIcon color="primary" />
          <Typography variant="h6">Ask about this supplier</Typography>
        </Stack>
        <Typography color="text.secondary" variant="body2" sx={{ mb: 2.5 }}>
          Answers are limited to this supplier's indexed documents and include source citations.
        </Typography>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ md: 'flex-start' }}>
          <TextField
            fullWidth
            multiline
            minRows={2}
            label="Question"
            placeholder="What do the uploaded documents say about this supplier?"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            disabled={asking || supplier.extracted_fields.length === 0}
          />
          <Button
            variant="contained"
            startIcon={asking ? <CircularProgress size={18} color="inherit" /> : <QuestionAnswerRoundedIcon />}
            disabled={asking || question.trim().length < 3 || supplier.extracted_fields.length === 0}
            onClick={handleAskQuestion}
            sx={{ minWidth: 150, minHeight: 56 }}
          >
            {asking ? 'Asking...' : 'Ask question'}
          </Button>
        </Stack>
        {questionResponse && (
          <Alert severity={questionResponse.information_found ? 'success' : 'info'} sx={{ mt: 2.5 }}>
            <Typography fontWeight={650}>{questionResponse.answer}</Typography>
            {questionResponse.citations.length > 0 && (
              <Stack spacing={1} sx={{ mt: 1.5 }}>
                {questionResponse.citations.map((citation) => (
                  <Box key={citation.chunk_id}>
                    <Typography variant="caption" fontWeight={700}>{citation.filename} / page {citation.page_number}</Typography>
                    <Typography variant="body2">{citation.excerpt}</Typography>
                  </Box>
                ))}
              </Stack>
            )}
            <Typography variant="caption" display="block" sx={{ mt: 1.5 }}>
              {questionResponse.run.model} / {questionResponse.run.retrieval_count} retrieved chunks / {(questionResponse.run.latency_ms / 1000).toFixed(1)}s
            </Typography>
          </Alert>
        )}
      </CardContent></Card>

      <Card><CardContent sx={{ p: { xs: 3, md: 4 } }}>
        <Typography variant="h6">Extracted review fields</Typography>
        <Typography color="text.secondary" variant="body2" sx={{ mb: 2.5 }}>Values include their source page and model confidence for human review.</Typography>
        {supplier.extracted_fields.length === 0 ? (
          <Alert severity="info">No fields have been extracted. Process the requested documents first.</Alert>
        ) : (
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0, 1fr))' }, gap: 2 }}>
            {supplier.extracted_fields.map((field) => {
              const sourceDocument = supplier.documents.find((document) => document.id === field.document_id)
              return (
                <Box key={field.id} sx={{ p: 2, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
                    <Typography variant="caption" color="text.secondary" fontWeight={700}>{fieldLabels[field.field_name] ?? field.field_name}</Typography>
                    <Stack direction="row" spacing={0.5} alignItems="center">
                      <Chip
                        size="small"
                        color={field.needs_review ? 'warning' : 'success'}
                        variant="outlined"
                        label={field.needs_review ? 'Review' : `${Math.round(field.confidence * 100)}%`}
                      />
                      <Tooltip title="Correct field">
                        <IconButton size="small" disabled={finalized} onClick={() => openFieldEditor(field)}>
                          <EditRoundedIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Stack>
                  </Stack>
                  <Typography fontWeight={650} sx={{ my: 1, overflowWrap: 'anywhere' }}>{field.value}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    {sourceDocument?.filename ?? 'Source document'} / page {field.page_number} / {Math.round(field.confidence * 100)}% confidence
                  </Typography>
                  {field.needs_review && (
                    <Alert severity="warning" sx={{ mt: 1.5, py: 0.25 }}>
                      <Typography variant="body2">{fieldReviewMessage(field, sourceDocument)}</Typography>
                    </Alert>
                  )}
                </Box>
              )
            })}
          </Box>
        )}
      </CardContent></Card>

      <Card><CardContent sx={{ p: { xs: 3, md: 4 } }}>
        <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ md: 'center' }} spacing={2}>
          <Box>
            <Stack direction="row" spacing={1} alignItems="center">
              <FactCheckRoundedIcon color="primary" />
              <Typography variant="h6">Compliance and human decision</Typography>
            </Stack>
            <Typography color="text.secondary" variant="body2" sx={{ mt: 0.75 }}>
              Deterministic checks control approval. AI fields remain editable until a final decision.
            </Typography>
          </Box>
          <Button
            variant="outlined"
            startIcon={checkingCompliance ? <CircularProgress size={18} /> : <FactCheckRoundedIcon />}
            disabled={checkingCompliance || supplier.extracted_fields.length === 0 || finalized}
            onClick={handleRunCompliance}
          >
            {checkingCompliance ? 'Checking...' : supplier.compliance_results.length ? 'Rerun checks' : 'Run checks'}
          </Button>
        </Stack>

        {supplier.compliance_results.length === 0 ? (
          <Alert severity="info" sx={{ mt: 2.5 }}>Run compliance checks after processing and reviewing extracted fields.</Alert>
        ) : (
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0, 1fr))' }, gap: 1.5, mt: 2.5 }}>
            {supplier.compliance_results.map((result) => (
              <Box key={result.id} sx={{ p: 2, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                <Stack direction="row" justifyContent="space-between" spacing={1}>
                  <Typography fontWeight={700}>{ruleLabels[result.rule_code] ?? result.rule_code}</Typography>
                  <Chip
                    size="small"
                    color={result.status === 'pass' ? 'success' : result.status === 'fail' ? 'error' : 'warning'}
                    label={result.status.replaceAll('_', ' ')}
                  />
                </Stack>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>{result.message}</Typography>
              </Box>
            ))}
          </Box>
        )}

        <Divider sx={{ my: 3 }} />
        <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={2}>
          <Alert severity={approvalReady ? 'success' : 'warning'} sx={{ flex: 1 }}>
            {approvalReady ? 'Every mandatory check passed. Human approval is enabled.' : 'Approval remains blocked until every check passes.'}
          </Alert>
          <Stack direction="row" spacing={1}>
            <Button
              color="error"
              variant="outlined"
              startIcon={<BlockRoundedIcon />}
              disabled={finalized}
              onClick={() => setDecisionAction('reject')}
            >
              Reject
            </Button>
            <Button
              color="success"
              variant="contained"
              startIcon={<HowToRegRoundedIcon />}
              disabled={!approvalReady || finalized}
              onClick={() => setDecisionAction('approve')}
            >
              Approve and send to ERP
            </Button>
          </Stack>
        </Stack>
      </CardContent></Card>

      <Dialog open={fieldToEdit !== null} onClose={() => !savingField && setFieldToEdit(null)} fullWidth maxWidth="sm">
        <DialogTitle>Correct extracted field</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField
              label={fieldToEdit ? fieldLabels[fieldToEdit.field_name] ?? fieldToEdit.field_name : 'Value'}
              value={editedValue}
              onChange={(event) => setEditedValue(event.target.value)}
              multiline
              minRows={2}
              autoFocus
            />
            <TextField
              label="Source page"
              type="number"
              value={editedPage}
              onChange={(event) => setEditedPage(Math.max(1, Number(event.target.value)))}
              slotProps={{ htmlInput: { min: 1 } }}
            />
            <Alert severity="info">Saving sets reviewer confidence to 100% and invalidates previous compliance results.</Alert>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFieldToEdit(null)} disabled={savingField}>Cancel</Button>
          <Button variant="contained" onClick={handleSaveField} disabled={savingField || !editedValue.trim()}>
            {savingField ? 'Saving...' : 'Save correction'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={decisionAction !== null} onClose={() => !deciding && setDecisionAction(null)} fullWidth maxWidth="sm">
        <DialogTitle>{decisionAction === 'approve' ? 'Approve supplier?' : 'Reject supplier?'}</DialogTitle>
        <DialogContent>
          {decisionAction === 'approve' ? (
            <DialogContentText>
              This confirms human review, finalizes the supplier, and creates its record in the mock ERP. The documents and extracted fields will be locked.
            </DialogContentText>
          ) : (
            <Stack spacing={2} sx={{ pt: 1 }}>
              <DialogContentText>Provide an auditable rejection reason. The supplier will be finalized without an ERP record.</DialogContentText>
              <TextField
                label="Rejection reason"
                value={rejectionReason}
                onChange={(event) => setRejectionReason(event.target.value)}
                multiline
                minRows={3}
                autoFocus
              />
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDecisionAction(null)} disabled={deciding}>Cancel</Button>
          <Button
            color={decisionAction === 'approve' ? 'success' : 'error'}
            variant="contained"
            onClick={handleDecision}
            disabled={deciding || (decisionAction === 'reject' && rejectionReason.trim().length < 10)}
          >
            {deciding ? 'Saving decision...' : decisionAction === 'approve' ? 'Confirm approval' : 'Confirm rejection'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={documentToDelete !== null} onClose={() => !deleting && setDocumentToDelete(null)}>
        <DialogTitle>Delete uploaded document?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            {documentToDelete?.filename} will be removed. Its document category will become available for a replacement upload.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDocumentToDelete(null)} disabled={deleting}>Cancel</Button>
          <Button color="error" variant="contained" onClick={handleDelete} disabled={deleting}>
            {deleting ? 'Deleting...' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  )
}
