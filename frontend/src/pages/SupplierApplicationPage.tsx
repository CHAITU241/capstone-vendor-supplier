import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded'
import CloudUploadRoundedIcon from '@mui/icons-material/CloudUploadRounded'
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import { Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Divider, IconButton, MenuItem, Stack, Step, StepLabel, Stepper, TextField, Tooltip, Typography } from '@mui/material'
import { useCallback, useEffect, useState, type ChangeEvent } from 'react'
import { api } from '../api/client'
import { downloadOriginal, openOriginal } from '../api/openOriginal'
import { evidenceDownloadFilename, supplierReference } from '../api/supplierReference'
import type { DocumentRevision, DocumentType, PolicyCatalog, SupplierApplication } from '../api/types'
import { useAuth } from '../auth/AuthContext'

const fallbackLabels: Record<DocumentType, string> = {
  registration: 'Business registration',
  tax: 'Tax registration',
  insurance: 'Insurance certificate',
  bank: 'Bank account verification',
}

export function SupplierApplicationPage() {
  const { session } = useAuth()
  const [application, setApplication] = useState<SupplierApplication | null>(null)
  const [history, setHistory] = useState<DocumentRevision[]>([])
  const [catalog, setCatalog] = useState<PolicyCatalog | null>(null)
  const [step, setStep] = useState(0)
  const [category, setCategory] = useState('')
  const [subcategory, setSubcategory] = useState('')
  const [name, setName] = useState('')
  const [email, setEmail] = useState(session?.email || '')
  const [taxReference, setTaxReference] = useState('')
  const [bankAccountNumber, setBankAccountNumber] = useState('')
  const [bankIfsc, setBankIfsc] = useState('')
  const [selected, setSelected] = useState<{ type: DocumentType; file: File } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    const [result, archived] = await Promise.all([api.getApplication(), api.applicationDocumentHistory()])
    setApplication(result)
    setHistory(archived)
    setCategory(result.category || '')
    setSubcategory(result.subcategory || '')
    setName(result.name === 'New application' ? '' : result.name)
    setEmail(result.contact_email || session?.email || '')
    setTaxReference(result.tax_reference || '')
    setBankAccountNumber(result.bank_account_number || '')
    setBankIfsc(result.bank_ifsc || '')
    setStep(!result.category ? 0 : result.country !== 'India' || result.name === 'New application' ||
      !result.tax_reference || !result.bank_account_number || !result.bank_ifsc ? 1 : 2)
  }, [session?.email])

  useEffect(() => {
    void Promise.all([load(), api.getPolicy().then(setCatalog)]).catch((err: Error) => setError(err.message))
  }, [load])

  useEffect(() => {
    const correcting = application?.status === 'new' || application?.documents.some((document) => document.review_status === 'disputed')
    if (!application?.submitted_at || correcting || ['approved', 'rejected'].includes(application.status)) return
    const timer = window.setInterval(() => {
      void load().catch((err: Error) => setError(err.message))
    }, 10_000)
    return () => window.clearInterval(timer)
  }, [application?.status, application?.submitted_at, load])

  useEffect(() => {
    if (application?.category && !application.submitted_at && catalog &&
        !catalog.categories.some((item) => item.code === application.category && item.subcategories.some((sub) => sub.code === application.subcategory))) {
      setStep(0) // Existing drafts made with the old illustrative taxonomy need a new primary code.
    }
  }, [application?.category, application?.subcategory, application?.submitted_at, catalog])

  async function saveCategory() {
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await api.saveApplication({ category, subcategory })
      setApplication(result); setStep(1); setNotice('Category saved. You can return to this application later.')
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not save category.') }
    finally { setBusy(false) }
  }

  async function saveDetails() {
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await api.saveApplication({ category, subcategory, name: name.trim(), contact_email: email.trim(),
        tax_reference: taxReference.trim(), bank_account_number: bankAccountNumber.trim(), bank_ifsc: bankIfsc.trim() })
      setApplication(result); setStep(2); setNotice(application?.submitted_at ? 'Corrected business details saved. Review the evidence below, then resubmit.' : 'Details saved. Next, upload the documents.')
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not save details.') }
    finally { setBusy(false) }
  }

  async function uploadDocument(type: DocumentType) {
    if (!selected || selected.type !== type) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api.uploadApplicationDocument(type, selected.file)
      setSelected(null)
      await load()
      setNotice(`${application?.requirements.documents.find((item) => item.document_type === type)?.label ?? fallbackLabels[type] ?? type} uploaded.`)
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not upload document.') }
    finally { setBusy(false) }
  }

  async function removeDocument(id: string) {
    setBusy(true); setError(''); setNotice('')
    try {
      await api.deleteApplicationDocument(id)
      await load()
      setNotice('Document moved to upload history. You can upload a replacement.')
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not remove document.') }
    finally { setBusy(false) }
  }

  async function retryTextExtraction(id: string) {
    setBusy(true); setError(''); setNotice('')
    try {
      const document = await api.retryApplicationTextExtraction(id)
      await load()
      if (document.processing_status === 'failed') throw new Error(document.error_message || 'OCR could not read this document.')
      setNotice(`${document.filename} is ready.${document.ocr_pages.length ? ` OCR was used on page${document.ocr_pages.length === 1 ? '' : 's'} ${document.ocr_pages.join(', ')}.` : ''}`)
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not retry text extraction.') }
    finally { setBusy(false) }
  }

  async function submit() {
    setBusy(true); setError(''); setNotice('')
    try {
      const submittedApplication = await api.submitApplication()
      setApplication(submittedApplication)
      setStep(3)
      setNotice('Your application has been submitted to the reviewer workspace.')
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not submit application.') }
    finally { setBusy(false) }
  }

  async function resubmit() {
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await api.resubmitApplication()
      setApplication(result)
      await load()
      setNotice('Your corrections have been resubmitted to the reviewer.')
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not resubmit the application.') }
    finally { setBusy(false) }
  }

  async function viewOriginal(id: string) {
    try { await openOriginal(() => api.applicationOriginal(id)) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not open the original document.') }
  }

  async function downloadFile(document: { id: string; document_type: string; revision: number; filename: string }) {
    const requirement = application?.requirements.documents.find((item) => item.document_type === document.document_type)
    const filename = evidenceDownloadFilename({ supplierId: application?.id ?? '', documentType: document.document_type,
      revision: document.revision, originalFilename: document.filename,
      requirementId: requirement?.requirement_id, label: requirement?.label ?? catalog?.requirements[document.document_type]?.label })
    try { await downloadOriginal(() => api.applicationOriginal(document.id), filename) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not download the original document.') }
  }

  if ((!application || !catalog) && !error) return <Box sx={{ display: 'grid', placeItems: 'center', py: 8 }}><CircularProgress /></Box>
  if (!application) return <Alert severity="error">{error}</Alert>
  const categoryOptions = catalog?.categories ?? []
  const selectedCategory = categoryOptions.find((item) => item.code === category)
  const selectedSubcategory = selectedCategory?.subcategories.find((item) => item.code === subcategory)
  const plainLanguage = (value: string) => value
    .replace(/\b(?:TECH|PROF|WORK|FAC|FOOD|LOG|GOODS|SENS)-[A-Z]+\b/g,
      (code) => categoryOptions.flatMap((item) => item.subcategories).find((item) => item.code === code)?.label ?? code)
    .replace(/\b[A-Z]+(?:-[A-Z]+)?-\d{3}(?:\.R\d)?\b/g,
      (code) => catalog?.requirements[code.split('.')[0]]?.label.toLowerCase() ?? 'the requested document')
  const submitted = Boolean(application.submitted_at)
  const documents = new Map(application.documents.map((document) => [document.document_type, document]))
  const required = new Set(application.requirements.documents.map((item) => item.document_type))
  const extras = application.documents.filter((document) => !required.has(document.document_type))
  const missing = application.requirements.documents.filter((item) => documents.get(item.document_type)?.processing_status !== 'ready')
  const flaggedDocuments = application.documents.filter((document) => document.review_status === 'disputed')
  const correctionMode = submitted && (flaggedDocuments.length > 0 || application.status === 'new')

  return <Stack spacing={3} maxWidth={860} mx="auto">
    <Box><Typography variant="h4">Your supplier application</Typography>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ sm: 'center' }} sx={{ mt: 1 }}>
        <Chip label={`Supplier reference: ${supplierReference(application.id)}`} size="small" variant="outlined" />
        <Typography color="text.secondary">Signed in as {session?.email}. Your completed steps and uploaded files are saved to this account.</Typography>
      </Stack></Box>
    <Stepper activeStep={submitted ? 3 : step} alternativeLabel sx={{ py: 2 }}>
      {['Category', 'Business details', 'Documents'].map((label) => <Step key={label}><StepLabel>{label}</StepLabel></Step>)}
    </Stepper>
    {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}
    {notice && <Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
    {submitted ? correctionMode
      ? <Alert severity="warning"><strong>{flaggedDocuments.length > 0 ? 'Reviewer changes requested.' : 'Corrections in progress.'}</strong> You can correct the submitted business details below and replace evidence specifically flagged by the reviewer. Resubmit when the application is ready.</Alert>
      : <Alert severity="success">Application submitted. A reviewer can now see your details and documents. Your current status is <strong>{application.status.replace('_', ' ')}</strong>.</Alert>
      : null}

    <Card><CardContent sx={{ p: { xs: 3, md: 4 }, '&:last-child': { pb: 4 } }}>
      {!submitted && step === 0 && <Stack spacing={3}>
        <Box><Typography variant="h5">1. What does your business provide?</Typography><Typography color="text.secondary" sx={{ mt: 0.75 }}>Choose the service that best describes what you provide. If your work spans several areas, choose the main service and your reviewer can confirm the fit.</Typography></Box>
        <TextField select label="Category" value={category} onChange={(event) => { setCategory(event.target.value); setSubcategory('') }} required>
          {categoryOptions.map((item) => <MenuItem key={item.code} value={item.code}>{item.label}</MenuItem>)}
        </TextField>
        <TextField select label="Subcategory" value={subcategory} onChange={(event) => setSubcategory(event.target.value)} disabled={!category} required>
          {(selectedCategory?.subcategories ?? []).map((item) => <MenuItem key={item.code} value={item.code}>{item.label}</MenuItem>)}
        </TextField>
        {selectedSubcategory && <Alert severity="info">{selectedSubcategory.definition} Examples: {selectedSubcategory.examples} {plainLanguage(selectedSubcategory.boundary)}</Alert>}
        <Button onClick={() => void saveCategory()} disabled={busy || !category || !subcategory} variant="contained" size="large">Save and continue</Button>
      </Stack>}

      {!submitted && step === 1 && <Stack spacing={3}>
        <Box><Typography variant="h5">2. Tell us about your business</Typography><Typography color="text.secondary" sx={{ mt: 0.75 }}>{selectedCategory?.label} / {selectedSubcategory?.label}</Typography></Box>
        <TextField label="Registered business name" required value={name} onChange={(event) => setName(event.target.value)} inputProps={{ maxLength: 200 }} />
        <TextField label="Contact email" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
        <TextField label="PAN / tax reference" required value={taxReference} onChange={(event) => setTaxReference(event.target.value)} helperText="Enter the reference shown on your tax document." />
        <TextField label="Bank account number" required value={bankAccountNumber} onChange={(event) => setBankAccountNumber(event.target.value)} helperText="Enter the account number shown on your bank document." />
        <TextField label="Bank IFSC" required value={bankIfsc} onChange={(event) => setBankIfsc(event.target.value)} helperText="Enter the IFSC shown on your bank document." />
        <Stack direction="row" spacing={1}><Button startIcon={<ArrowBackRoundedIcon />} onClick={() => setStep(0)}>Category</Button>
          <Button onClick={() => void saveDetails()} disabled={busy || name.trim().length < 2 || !email.trim() || !taxReference.trim() || !bankAccountNumber.trim() || !bankIfsc.trim()} variant="contained" size="large">Save and continue to documents</Button></Stack>
      </Stack>}

      {(step === 2 || submitted) && <Stack spacing={3}>
        <Box><Typography variant="h5">{submitted ? 'Application summary' : '3. Upload your documents'}</Typography>
          <Typography color="text.secondary" sx={{ mt: 0.75 }}>{application.name} · {selectedCategory?.label ?? application.category} / {selectedSubcategory?.label ?? application.subcategory}</Typography></Box>
        <Divider />
        {correctionMode && <Box sx={{ p: 2, border: '1px solid', borderColor: 'warning.main', bgcolor: 'rgba(237,108,2,.04)', borderRadius: 2 }}>
          <Typography variant="h6">Correct submitted business details</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Category remains locked because changing it would change the evidence checklist.</Typography>
          <Stack spacing={2}>
            <TextField label="Registered business name" required value={name} onChange={(event) => setName(event.target.value)} inputProps={{ maxLength: 200 }} />
            <TextField label="Contact email" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
            <TextField label="PAN / tax reference" required value={taxReference} onChange={(event) => setTaxReference(event.target.value)} />
            <TextField label="Bank account number" required value={bankAccountNumber} onChange={(event) => setBankAccountNumber(event.target.value)} />
            <TextField label="Bank IFSC" required value={bankIfsc} onChange={(event) => setBankIfsc(event.target.value)} />
            <Button variant="outlined" disabled={busy || name.trim().length < 2 || !email.trim() || !taxReference.trim() || !bankAccountNumber.trim() || !bankIfsc.trim()} onClick={() => void saveDetails()}>Save corrected details</Button>
          </Stack>
        </Box>}
        <Alert severity="info">These documents are based on the service you selected. A reviewer will check their contents after you submit.</Alert>
        <Typography variant="body2" color="text.secondary">Upload one PDF, PNG, JPEG or UTF-8 text file (up to 10 MB) for each item. Scanned pages are read with OCR. If an item asks for two pieces of evidence, combine them into one PDF.</Typography>
        {application.requirements.documents.map(({ document_type: type, requirement_id: requirementId, label, why, accepted_evidence, required_fields, checks }) => {
          const document = documents.get(type)
          const flagged = document?.review_status === 'disputed'
          return <Stack key={type} direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={1.5} sx={{ p: 2, border: '1px solid', borderColor: flagged ? 'warning.main' : 'divider', bgcolor: flagged ? 'rgba(237,108,2,.06)' : 'transparent', borderRadius: 2 }}>
            <Box sx={{ flex: 1 }}><Stack direction="row" alignItems="center" spacing={0.5}>
              <Typography fontWeight={700}>{label}</Typography>
              <Tooltip title={requirementId ? `Policy requirement: ${requirementId}` : 'Legacy document requirement'} arrow>
                <IconButton size="small" aria-label={requirementId ? `Policy requirement ${requirementId}` : 'Legacy document requirement'} sx={{ p: 0.25, color: 'info.main' }}><InfoOutlinedIcon sx={{ fontSize: 18 }} /></IconButton>
              </Tooltip>
            </Stack><Typography variant="body2" color="text.secondary">{plainLanguage(why)}</Typography>
              {accepted_evidence && <Typography variant="body2" sx={{ mt: 0.5 }}><strong>Submit:</strong> {plainLanguage(accepted_evidence)}</Typography>}
              {required_fields && <Typography variant="body2"><strong>Include:</strong> {plainLanguage(required_fields)}</Typography>}
              {checks.length > 0 && <Box component="details" sx={{ mt: 0.5 }}><Typography component="summary" variant="body2" sx={{ cursor: 'pointer' }}>What reviewers will check</Typography>
                {checks.map((check) => <Typography key={check} variant="body2">{plainLanguage(check)}</Typography>)}</Box>}
              <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>{document ? document.filename : selected?.type === type ? selected.file.name : 'Not uploaded yet'}</Typography>
              {document?.ocr_pages.length ? <Typography variant="caption" color="info.dark" display="block">OCR used on page{document.ocr_pages.length === 1 ? '' : 's'} {document.ocr_pages.join(', ')}</Typography> : null}
              {document?.ocr_warnings.map((warning) => <Typography key={warning} variant="caption" color="warning.dark" display="block">{warning}</Typography>)}
              {document?.processing_status === 'failed' && <Alert severity="error" sx={{ mt: 1, py: .25 }}>{document.error_message || 'Text extraction failed.'}</Alert>}
              {flagged && <Alert severity="warning" sx={{ mt: 1, py: 0.25 }}><strong>Reviewer feedback:</strong> {document.review_comment || 'The reviewer requested changes to this evidence.'}</Alert>}
            </Box>
            {document ? <Stack alignItems={{ sm: 'flex-end' }} spacing={1}>
              <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap" useFlexGap>
                {flagged && <Chip label="Changes requested" color="warning" size="small" />}
                <Chip label={document.processing_status === 'ready' ? 'Uploaded' : document.processing_status} color={document.processing_status === 'ready' ? 'success' : 'warning'} size="small" />
                <Button size="small" onClick={() => void viewOriginal(document.id)}>View original</Button>
                <Button size="small" onClick={() => void downloadFile(document)}>Download</Button>
                {!submitted && document.processing_status === 'failed' && <Button size="small" disabled={busy} onClick={() => void retryTextExtraction(document.id)}>Retry OCR</Button>}
                {!submitted && <IconButton aria-label={`Remove ${label}`} disabled={busy} onClick={() => void removeDocument(document.id)}><DeleteOutlineRoundedIcon /></IconButton>}
              </Stack>
              {flagged && correctionMode && <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                <Button component="label" size="small" variant="outlined" startIcon={<CloudUploadRoundedIcon />}>Choose replacement
                  <input hidden type="file" accept="application/pdf,image/png,image/jpeg,text/plain,.pdf,.png,.jpg,.jpeg,.txt" onChange={(event: ChangeEvent<HTMLInputElement>) => {
                    const file = event.target.files?.[0]; if (file) setSelected({ type, file })
                    event.target.value = ''
                  }} />
                </Button>
                {selected?.type === type && <Typography variant="caption" sx={{ maxWidth: 220, overflowWrap: 'anywhere' }}>{selected.file.name}</Typography>}
                <Button size="small" variant="contained" disabled={busy || selected?.type !== type} onClick={() => void uploadDocument(type)}>Replace flagged document</Button>
              </Stack>}
            </Stack> : (!submitted || correctionMode) && <Stack direction="row" spacing={1}>
              <Button component="label" variant="outlined" startIcon={<CloudUploadRoundedIcon />}>Choose file
                <input hidden type="file" accept="application/pdf,image/png,image/jpeg,text/plain,.pdf,.png,.jpg,.jpeg,.txt" onChange={(event: ChangeEvent<HTMLInputElement>) => {
                  const file = event.target.files?.[0]; if (file) setSelected({ type, file })
                  event.target.value = ''
                }} />
              </Button>
              <Button variant="contained" disabled={busy || selected?.type !== type} onClick={() => void uploadDocument(type)}>Upload</Button>
            </Stack>}
          </Stack>
        })}
        {extras.length > 0 && <Alert severity="warning">Your details changed, so {extras.length === 1 ? 'a previously uploaded document is' : 'some previously uploaded documents are'} no longer in the checklist. Remove {extras.length === 1 ? 'it' : 'them'} before submitting.</Alert>}
        {extras.map((document) => <Stack key={document.id} direction="row" justifyContent="space-between" alignItems="center" sx={{ p: 2, border: '1px solid', borderColor: 'warning.main', borderRadius: 2 }}>
          <Box><Typography fontWeight={700}>{fallbackLabels[document.document_type] ?? catalog?.requirements[document.document_type]?.label ?? 'Previously requested document'} · not requested</Typography><Typography variant="body2">{document.filename}</Typography></Box>
          {!submitted && <IconButton aria-label={`Remove ${document.filename}`} disabled={busy} onClick={() => void removeDocument(document.id)}><DeleteOutlineRoundedIcon /></IconButton>}
        </Stack>)}
        {history.length > 0 && <Box>
          <Typography variant="h6">Previous uploads</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Original files are retained when you remove or replace them.</Typography>
          {history.map((item) => <Stack key={item.id} direction="row" alignItems="center" justifyContent="space-between" spacing={2} sx={{ py: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
            <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>{item.filename} · version {item.revision}</Typography>
            <Button size="small" onClick={() => void viewOriginal(item.id)}>View original</Button>
            <Button size="small" onClick={() => void downloadFile(item)}>Download</Button>
          </Stack>)}
        </Box>}
        {!submitted && <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1}>
          <Button startIcon={<ArrowBackRoundedIcon />} onClick={() => setStep(1)}>Edit details</Button>
          <Button variant="contained" size="large" disabled={busy || application.requirements.documents.length === 0 || missing.length > 0 || extras.length > 0} onClick={() => void submit()}>
            {busy ? 'Submitting application...' : 'Submit application for review'}
          </Button>
        </Stack>}
        {correctionMode && <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="flex-end" spacing={1}>
          <Button variant="contained" size="large" disabled={busy || application.requirements.documents.length === 0 || missing.length > 0 || extras.length > 0} onClick={() => void resubmit()}>
            {busy ? 'Resubmitting corrections...' : 'Resubmit corrections for review'}
          </Button>
        </Stack>}
      </Stack>}
    </CardContent></Card>
  </Stack>
}
