import BusinessRoundedIcon from '@mui/icons-material/BusinessRounded'
import DescriptionRoundedIcon from '@mui/icons-material/DescriptionRounded'
import { Alert, Box, Button, Card, CardActionArea, CardContent, CircularProgress, Stack, Typography } from '@mui/material'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { SupplierSummary } from '../api/types'
import { StatusChip } from '../components/StatusChip'

export function DashboardPage() {
  const [suppliers, setSuppliers] = useState<SupplierSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api.listSuppliers()
      .then(setSuppliers)
      .catch((requestError: Error) => setError(requestError.message))
      .finally(() => setLoading(false))
  }, [])

  return (
    <Stack spacing={4}>
      <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }} spacing={2}>
        <Box>
          <Typography variant="h4">Reviewer workspace</Typography>
          <Typography color="text.secondary" sx={{ mt: 0.75 }}>Review submitted supplier applications and their documents.</Typography>
        </Box>
        <Button component={Link} to="/review/erp" variant="outlined">View mock ERP records</Button>
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}
      {loading && <Box sx={{ display: 'grid', placeItems: 'center', py: 8 }}><CircularProgress /></Box>}
      {!loading && !error && suppliers.length === 0 && (
        <Card><CardContent sx={{ py: 7, textAlign: 'center' }}>
          <BusinessRoundedIcon sx={{ fontSize: 48, color: 'primary.main', mb: 1 }} />
          <Typography variant="h6">No applications submitted yet</Typography>
          <Typography color="text.secondary">Submitted applications will appear here for review. Supplier drafts stay in the supplier workspace.</Typography>
        </CardContent></Card>
      )}

      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(2, 1fr)' }, gap: 2 }}>
        {suppliers.map((supplier) => (
          <Card key={supplier.id}>
            <CardActionArea component={Link} to={`/review/suppliers/${supplier.id}`}>
              <CardContent>
                <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={2}>
                  <Box>
                    <Typography variant="h6">{supplier.name}</Typography>
                    {supplier.category && <Typography color="primary" variant="body2">{supplier.category} / {supplier.subcategory}</Typography>}
                    <Typography color="text.secondary" variant="body2">{supplier.country || 'Country not provided'}</Typography>
                  </Box>
                  <StatusChip status={supplier.status} />
                </Stack>
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 3, color: 'text.secondary' }}>
                  <DescriptionRoundedIcon fontSize="small" />
                  <Typography variant="body2">{supplier.document_count} document{supplier.document_count === 1 ? '' : 's'}</Typography>
                </Stack>
              </CardContent>
            </CardActionArea>
          </Card>
        ))}
      </Box>
    </Stack>
  )
}
