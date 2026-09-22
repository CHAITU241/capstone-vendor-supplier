import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded'
import StorageRoundedIcon from '@mui/icons-material/StorageRounded'
import { Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Stack, Typography } from '@mui/material'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { ErpRecord } from '../api/types'

export function ErpRecordsPage() {
  const [records, setRecords] = useState<ErpRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api.listErpRecords().then(setRecords).catch((err: Error) => setError(err.message)).finally(() => setLoading(false))
  }, [])

  return <Stack spacing={3}>
    <Button component={Link} to="/review" startIcon={<ArrowBackRoundedIcon />} sx={{ alignSelf: 'flex-start' }}>Back to reviewer workspace</Button>
    <Box><Typography variant="h4">Mock ERP supplier master</Typography><Typography color="text.secondary" sx={{ mt: .75 }}>Records retrieved from the downstream mock ERP through MCP—not from the onboarding supplier table.</Typography></Box>
    {error && <Alert severity="error">{error}</Alert>}
    {loading && <Box sx={{ display: 'grid', placeItems: 'center', py: 8 }}><CircularProgress /></Box>}
    {!loading && !error && records.length === 0 && <Card><CardContent sx={{ py: 7, textAlign: 'center' }}><StorageRoundedIcon sx={{ fontSize: 48, color: 'primary.main', mb: 1 }} /><Typography variant="h6">No ERP supplier records yet</Typography><Typography color="text.secondary">A record appears here only after policy review, ERP validation, and explicit reviewer approval.</Typography></CardContent></Card>}
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0, 1fr))' }, gap: 2 }}>
      {records.map((record) => <Card key={record.erp_supplier_id}><CardContent><Stack direction="row" justifyContent="space-between" spacing={2}><Box sx={{ minWidth: 0 }}><Typography variant="h6">{record.legal_name}</Typography><Typography variant="body2" color="primary">{record.erp_supplier_id}</Typography><Typography variant="body2" color="text.secondary">Portal reference: {record.supplier_reference ?? 'Not provided'}</Typography></Box><Chip size="small" color="success" label={record.status} /></Stack><Stack spacing={.5} sx={{ mt: 2 }}><Typography variant="body2"><strong>Tax reference:</strong> {record.tax_reference}</Typography><Typography variant="body2"><strong>Classification:</strong> {record.category} / {record.subcategory}</Typography><Typography variant="caption" color="text.secondary">Created {record.created_at ? new Date(record.created_at).toLocaleString() : 'date unavailable'}</Typography></Stack><Button component={Link} to={`/review/suppliers/${record.source_supplier_id}`} size="small" sx={{ mt: 1.5 }}>Open onboarding record</Button></CardContent></Card>)}
    </Box>
  </Stack>
}
