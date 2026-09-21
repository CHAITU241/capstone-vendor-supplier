import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded'
import AssignmentTurnedInRoundedIcon from '@mui/icons-material/AssignmentTurnedInRounded'
import BusinessRoundedIcon from '@mui/icons-material/BusinessRounded'
import DescriptionRoundedIcon from '@mui/icons-material/DescriptionRounded'
import { Alert, Box, Button, Card, CardContent, Chip, Stack, Typography } from '@mui/material'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'

export function HomePage() {
  const { session, setSession } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function enterReviewerDemo() {
    setLoading(true)
    setError('')
    try {
      setSession(await api.reviewerDemo())
      navigate('/review')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not open reviewer workspace.')
    } finally { setLoading(false) }
  }

  return (
    <Stack spacing={5}>
      <Box sx={{ py: { xs: 1, md: 4 }, maxWidth: 790 }}>
        <Chip label="SUPPLIER ONBOARDING" color="secondary" variant="outlined" size="small" sx={{ fontWeight: 700, mb: 2 }} />
        <Typography component="h1" sx={{ fontSize: { xs: 38, md: 55 }, lineHeight: 1.1, letterSpacing: '-0.045em', fontWeight: 780 }}>
          A clear path from application to approval.
        </Typography>
        <Typography color="text.secondary" sx={{ fontSize: { xs: 17, md: 19 }, mt: 2, maxWidth: 650 }}>
          Choose your workspace to get started. Suppliers can save their application and return to it later; reviewers can track submitted cases.
        </Typography>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(2, 1fr)' }, gap: 3 }}>
        <Card sx={{ borderRadius: 3, background: 'linear-gradient(145deg, #FFFFFF 60%, #EFF6FF)' }}>
          <CardContent sx={{ p: { xs: 3, md: 4 }, '&:last-child': { pb: 4 } }}>
            <Box sx={{ width: 52, height: 52, display: 'grid', placeItems: 'center', borderRadius: 2.5, bgcolor: '#DBEAFE', color: 'primary.main', mb: 3 }}><BusinessRoundedIcon /></Box>
            <Typography variant="h5">I'm a supplier</Typography>
            <Typography color="text.secondary" sx={{ mt: 1, mb: 3, minHeight: 50 }}>Apply, add your business details, upload documents, and pick up where you left off.</Typography>
            {session?.role === 'supplier'
              ? <Button component={Link} to="/supplier/application" variant="contained" endIcon={<ArrowForwardRoundedIcon />} size="large">Continue application</Button>
              : <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ xs: 'stretch', sm: 'center' }}>
                  <Button component={Link} to="/supplier/login?mode=register" variant="contained" endIcon={<ArrowForwardRoundedIcon />} size="large">Create account</Button>
                  <Button component={Link} to="/supplier/login?mode=login" variant="outlined" size="large">Sign in</Button>
                </Stack>}
          </CardContent>
        </Card>
        <Card sx={{ borderRadius: 3, background: 'linear-gradient(145deg, #FFFFFF 60%, #F3E8FF)' }}>
          <CardContent sx={{ p: { xs: 3, md: 4 }, '&:last-child': { pb: 4 } }}>
            <Box sx={{ width: 52, height: 52, display: 'grid', placeItems: 'center', borderRadius: 2.5, bgcolor: '#EDE9FE', color: 'tertiary.main', mb: 3 }}><AssignmentTurnedInRoundedIcon /></Box>
            <Typography variant="h5">I'm a reviewer</Typography>
            <Typography color="text.secondary" sx={{ mt: 1, mb: 3, minHeight: 50 }}>Open the company workspace to review submitted applications, documents, and checks.</Typography>
            {session?.role === 'reviewer'
              ? <Button component={Link} to="/review" variant="outlined" endIcon={<ArrowForwardRoundedIcon />} size="large">Continue reviewing</Button>
              : <Button variant="outlined" endIcon={<ArrowForwardRoundedIcon />} size="large" onClick={() => void enterReviewerDemo()} disabled={loading}>{loading ? 'Opening...' : 'Enter reviewer demo'}</Button>}
          </CardContent>
        </Card>
      </Box>
      <Stack direction="row" spacing={1.5} alignItems="center" sx={{ color: 'text.secondary' }}>
        <DescriptionRoundedIcon fontSize="small" /><Typography variant="body2">Suppliers choose a category first, then complete details and upload documents.</Typography>
      </Stack>
    </Stack>
  )
}
