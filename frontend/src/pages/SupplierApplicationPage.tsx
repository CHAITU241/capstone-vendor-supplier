import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded'
import CloudUploadRoundedIcon from '@mui/icons-material/CloudUploadRounded'
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import { Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Divider, IconButton, MenuItem, Stack, Step, StepLabel, Stepper, TextField, Typography } from '@mui/material'
import { useCallback, useEffect, useState, type ChangeEvent } from 'react'
import { api } from '../api/client'
import type { DocumentType, PolicyCatalog, SupplierApplication } from '../api/types'
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
  const [catalog, setCatalog] = useState<PolicyCatalog | null>(null)
  const [step, setStep] = useState(0)
  const [category, setCategory] = useState('')
  const [subcategory, setSubcategory] = useState('')
  const [name, setName] = useState('')
  const [country, setCountry] = useState('India')
  const [email, setEmail] = useState(session?.email || '')
  const [taxReference, setTaxReference] = useState('')
  const [bankAccountNumber, setBankAccountNumber] = useState('')
  const [bankIfsc, setBankIfsc] = useState('')
  const [selected, setSelected] = useState<{ type: DocumentType; file: File } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    const result = await api.getApplication()
    setApplication(result)
    setCategory(result.category || '')
    setSubcategory(result.subcategory || '')
    setName(result.name === 'New application' ? '' : result.name)
    setCountry(result.country || 'India')
    setEmail(result.contact_email || session?.email || '')
    setTaxReference(result.tax_reference || '')
    setBankAccountNumber(result.bank_account_number || '')
    setBankIfsc(result.bank_ifsc || '')
    setStep(!result.category ? 0 : !result.country || result.name === 'New application' ? 1 : 2)
  }, [session?.email])

  useEffect(() => {
    void Promise.all([load(), api.getPolicy().then(setCatalog)]).catch((err: Error) => setError(err.message))
  }, [load])

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
      const result = await api.saveApplication({ category, subcategory, name: name.trim(), country, contact_email: email.trim(),
        tax_reference: taxReference.trim(), bank_account_number: bankAccountNumber.trim(), bank_ifsc: bankIfsc.trim() })
      setApplication(result); setStep(2); setNotice('Details saved. Next, upload the documents.')
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not save details.') }
    finally { setBusy(false) }
  }

  async function uploadDocument(type: DocumentType) {
    if (!selected || selected.type !== type) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api.uploadApplicationDocument(type, selected.file)
      setSelected(null)
      setApplication(await api.getApplication())
      setNotice(`${application?.requirements.documents.find((item) => item.document_type === type)?.label ?? fallbackLabels[type] ?? type} uploaded.`)
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not upload document.') }
    finally { setBusy(false) }
  }

  async function removeDocument(id: string) {
    setBusy(true); setError(''); setNotice('')
    try {
      await api.deleteApplicationDocument(id)
      setApplication(await api.getApplication())
      setNotice('Document removed. You can upload a replacement.')
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not remove document.') }
    finally { setBusy(false) }
  }

  async function submit() {
    setBusy(true); setError(''); setNotice('')
    try {
      setApplication(await api.submitApplication())
      setNotice('Your application has been submitted to the reviewer workspace.')
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not submit application.') }
    finally { setBusy(false) }
  }

  if ((!application || !catalog) && !error) return <Box sx={{ display: 'grid', placeItems: 'center', py: 8 }}><CircularProgress /></Box>
  if (!application) return <Alert severity="error">{error}</Alert>
  const categoryOptions = catalog?.categories ?? []
  const selectedCategory = categoryOptions.find((item) => item.code === category)
  const selectedSubcategory = selectedCategory?.subcategories.find((item) => item.code === subcategory)
  const submitted = Boolean(application.submitted_at)
  const documents = new Map(application.documents.map((document) => [document.document_type, document]))
  const required = new Set(application.requirements.documents.map((item) => item.document_type))
  const extras = application.documents.filter((document) => !required.has(document.document_type))
  const missing = application.requirements.documents.filter((item) => documents.get(item.document_type)?.processing_status !== 'ready')

  return <Stack spacing={3} maxWidth={860} mx="auto">
    <Box><Typography variant="h4">Your supplier application</Typography>
      <Typography color="text.secondary" sx={{ mt: 1 }}>Signed in as {session?.email}. Your completed steps and uploaded files are saved to this account.</Typography></Box>
    <Stepper activeStep={submitted ? 3 : step} alternativeLabel sx={{ py: 2 }}>
      {['Category', 'Business details', 'Documents'].map((label) => <Step key={label}><StepLabel>{label}</StepLabel></Step>)}
    </Stepper>
    {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}
    {notice && <Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
    {submitted ? <Alert severity="success">Application submitted. A reviewer can now see your details and documents. Your current status is <strong>{application.status.replace('_', ' ')}</strong>.</Alert> : null}

    <Card><CardContent sx={{ p: { xs: 3, md: 4 }, '&:last-child': { pb: 4 } }}>
      {!submitted && step === 0 && <Stack spacing={3}>
        <Box><Typography variant="h5">1. What does your business provide?</Typography><Typography color="text.secondary" sx={{ mt: 0.75 }}>Choose one primary service under the synthetic policy v1.1. If your work spans several categories, ask the reviewer to confirm the best fit.</Typography></Box>
        <TextField select label="Category" value={category} onChange={(event) => { setCategory(event.target.value); setSubcategory('') }} required>
          {categoryOptions.map((item) => <MenuItem key={item.code} value={item.code}>{item.label} ({item.code})</MenuItem>)}
        </TextField>
        <TextField select label="Subcategory" value={subcategory} onChange={(event) => setSubcategory(event.target.value)} disabled={!category} required>
          {(selectedCategory?.subcategories ?? []).map((item) => <MenuItem key={item.code} value={item.code}>{item.label} ({item.code})</MenuItem>)}
        </TextField>
        {selectedSubcategory && <Alert severity="info">{selectedSubcategory.definition} Examples: {selectedSubcategory.examples} Boundary: {selectedSubcategory.boundary}</Alert>}
        <Button onClick={() => void saveCategory()} disabled={busy || !category || !subcategory} variant="contained" size="large">Save and continue</Button>
      </Stack>}

      {!submitted && step === 1 && <Stack spacing={3}>
        <Box><Typography variant="h5">2. Tell us about your business</Typography><Typography color="text.secondary" sx={{ mt: 0.75 }}>{selectedCategory?.label} / {selectedSubcategory?.label}</Typography></Box>
        <TextField label="Registered business name" required value={name} onChange={(event) => setName(event.target.value)} inputProps={{ maxLength: 200 }} />
        <TextField label="Country" required value={country} InputProps={{ readOnly: true }} helperText="Synthetic policy v1.1 covers India-based incorporated suppliers only." />
        <TextField label="Contact email" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
        <TextField label="PAN / tax reference" required value={taxReference} onChange={(event) => setTaxReference(event.target.value)} helperText="Must match the tax evidence you upload (BASE-002). Use synthetic data for the demo." />
        <TextField label="Bank account number" required value={bankAccountNumber} onChange={(event) => setBankAccountNumber(event.target.value)} helperText="Must match the bank evidence you upload (BASE-003). Use synthetic data for the demo." />
        <TextField label="Bank IFSC" required value={bankIfsc} onChange={(event) => setBankIfsc(event.target.value)} helperText="Must match the bank evidence you upload (BASE-003)." />
        <Stack direction="row" spacing={1}><Button startIcon={<ArrowBackRoundedIcon />} onClick={() => setStep(0)}>Category</Button>
          <Button onClick={() => void saveDetails()} disabled={busy || name.trim().length < 2 || !country || !email.trim() || !taxReference.trim() || !bankAccountNumber.trim() || !bankIfsc.trim()} variant="contained" size="large">Save and continue to documents</Button></Stack>
      </Stack>}

      {(step === 2 || submitted) && <Stack spacing={3}>
        <Box><Typography variant="h5">{submitted ? 'Application summary' : '3. Upload your documents'}</Typography>
          <Typography color="text.secondary" sx={{ mt: 0.75 }}>{application.name} · {application.category} / {application.subcategory} · {application.country}</Typography></Box>
        <Divider />
        <Alert severity="info">Synthetic policy checklist · {application.requirements.version}. {application.requirements.reason} The portal checks that files are present; a reviewer must verify their contents against the numbered checks.</Alert>
        <Typography variant="body2" color="text.secondary">Upload one text-based PDF or UTF-8 text file (up to 10 MB) for each requirement. For requirements with two evidence items, combine them into one PDF. Scanned images and image-only PDFs are not supported yet.</Typography>
        {application.requirements.documents.map(({ document_type: type, requirement_id, label, why, accepted_evidence, required_fields, checks, source }) => {
          const document = documents.get(type)
          return <Stack key={type} direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={1.5} sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
            <Box sx={{ flex: 1 }}><Typography fontWeight={700}>{requirement_id && `${requirement_id} · `}{label}</Typography><Typography variant="body2" color="text.secondary">{why}</Typography>
              {accepted_evidence && <Typography variant="body2" sx={{ mt: 0.5 }}><strong>Submit:</strong> {accepted_evidence}</Typography>}
              {required_fields && <Typography variant="body2"><strong>Include:</strong> {required_fields}</Typography>}
              {checks.length > 0 && <Box component="details" sx={{ mt: 0.5 }}><Typography component="summary" variant="body2" sx={{ cursor: 'pointer' }}>View policy checks and source</Typography>
                {checks.map((check, i) => <Typography key={i} variant="body2">{requirement_id}.R{i + 1}: {check}</Typography>)}
                <Typography variant="caption" color="text.secondary">Source: {source}</Typography></Box>}
              <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>{document ? document.filename : selected?.type === type ? selected.file.name : 'Not uploaded yet'}</Typography></Box>
            {document ? <Stack direction="row" alignItems="center" spacing={1}>
              <Chip label={document.processing_status === 'ready' ? 'Uploaded' : document.processing_status} color={document.processing_status === 'ready' ? 'success' : 'warning'} size="small" />
              {!submitted && <IconButton aria-label={`Remove ${label}`} disabled={busy} onClick={() => void removeDocument(document.id)}><DeleteOutlineRoundedIcon /></IconButton>}
            </Stack> : !submitted && <Stack direction="row" spacing={1}>
              <Button component="label" variant="outlined" startIcon={<CloudUploadRoundedIcon />}>Choose file
                <input hidden type="file" accept="application/pdf,text/plain,.pdf,.txt" onChange={(event: ChangeEvent<HTMLInputElement>) => {
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
          <Box><Typography fontWeight={700}>{fallbackLabels[document.document_type] ?? document.document_type} · not requested</Typography><Typography variant="body2">{document.filename}</Typography></Box>
          {!submitted && <IconButton aria-label={`Remove ${document.filename}`} disabled={busy} onClick={() => void removeDocument(document.id)}><DeleteOutlineRoundedIcon /></IconButton>}
        </Stack>)}
        {!submitted && <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1}>
          <Button startIcon={<ArrowBackRoundedIcon />} onClick={() => setStep(1)}>Edit details</Button>
          <Button variant="contained" size="large" disabled={busy || application.requirements.documents.length === 0 || missing.length > 0 || extras.length > 0} onClick={() => void submit()}>Submit application for review</Button>
        </Stack>}
      </Stack>}
    </CardContent></Card>
  </Stack>
}
