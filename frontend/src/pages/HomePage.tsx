import ArrowForwardRoundedIcon from '@mui/icons-material/ArrowForwardRounded'
import AssignmentTurnedInRoundedIcon from '@mui/icons-material/AssignmentTurnedInRounded'
import BusinessRoundedIcon from '@mui/icons-material/BusinessRounded'
import DescriptionRoundedIcon from '@mui/icons-material/DescriptionRounded'
import AdminPanelSettingsRoundedIcon from '@mui/icons-material/AdminPanelSettingsRounded'
import { Alert, Box, Button, Card, CardContent, Chip, Stack, Typography } from '@mui/material'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { AccessConfig } from '../api/types'
import { useAuth } from '../auth/AuthContext'

export function HomePage() {
  const { getSession, setSession } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState('')
  const [opening, setOpening] = useState<'reviewer' | 'admin' | null>(null)
  const [accessConfig, setAccessConfig] = useState<AccessConfig | null>(null)
  const supplierSession = getSession('supplier')
  const reviewerSession = getSession('reviewer')
  const adminSession = getSession('admin')

  useEffect(() => {
    void api.accessConfig()
      .then(setAccessConfig)
      .catch((err: Error) => setError(err.message))
  }, [])

  async function enterDemo(role: 'reviewer' | 'admin') {
    setOpening(role)
    setError('')
    try {
      setSession(role === 'reviewer' ? await api.reviewerDemo() : await api.adminDemo())
      navigate(role === 'reviewer' ? '/review' : '/admin')
    } catch (err) {
      setError(err instanceof Error ? err.message : `Could not open ${role} workspace.`)
    } finally { setOpening(null) }
  }

  return (
    <Stack spacing={5}>
      <Box sx={{ py: { xs: 1, md: 4 }, maxWidth: 790 }}>
        <Chip label="SUPPLIER ONBOARDING" color="secondary" variant="outlined" size="small" sx={{ fontWeight: 700, mb: 2 }} />
        <Typography component="h1" sx={{ fontSize: { xs: 38, md: 55 }, lineHeight: 1.1, letterSpacing: '-0.045em', fontWeight: 780 }}>
          A clear path from application to approval.
        </Typography>
        <Typography color="text.secondary" sx={{ fontSize: { xs: 17, md: 19 }, mt: 2, maxWidth: 650 }}>
          Choose your workspace to get started. Suppliers apply, reviewers assess evidence, and administrators monitor AI operations.
        </Typography>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(3, 1fr)' }, gap: 3 }}>
        <Card sx={{ borderRadius: 3, background: 'linear-gradient(145deg, #FFFFFF 60%, #EFF6FF)' }}>
          <CardContent sx={{ p: { xs: 3, md: 4 }, '&:last-child': { pb: 4 } }}>
            <Box sx={{ width: 52, height: 52, display: 'grid', placeItems: 'center', borderRadius: 2.5, bgcolor: '#DBEAFE', color: 'primary.main', mb: 3 }}><BusinessRoundedIcon /></Box>
            <Typography variant="h5">I'm a supplier</Typography>
            <Typography color="text.secondary" sx={{ mt: 1, mb: 3, minHeight: 50 }}>Apply, add your business details, upload documents, and pick up where you left off.</Typography>
            {supplierSession
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
            {reviewerSession
              ? <Button component={Link} to="/review" variant="outlined" endIcon={<ArrowForwardRoundedIcon />} size="large">Continue reviewing</Button>
              : accessConfig?.reviewer_auth_enabled
                ? <Button component={Link} to="/reviewer/login" variant="outlined" endIcon={<ArrowForwardRoundedIcon />} size="large">Reviewer sign in</Button>
                : <Button variant="outlined" endIcon={<ArrowForwardRoundedIcon />} size="large" onClick={() => void enterDemo('reviewer')} disabled={!accessConfig || opening !== null}>{opening === 'reviewer' ? 'Opening...' : 'Enter reviewer workspace'}</Button>}
          </CardContent>
        </Card>
        <Card sx={{ borderRadius: 3, background: 'linear-gradient(145deg, #FFFFFF 60%, #ECFDF5)' }}>
          <CardContent sx={{ p: { xs: 3, md: 4 }, '&:last-child': { pb: 4 } }}>
            <Box sx={{ width: 52, height: 52, display: 'grid', placeItems: 'center', borderRadius: 2.5, bgcolor: '#D1FAE5', color: 'success.dark', mb: 3 }}><AdminPanelSettingsRoundedIcon /></Box>
            <Typography variant="h5">I'm an administrator</Typography>
            <Typography color="text.secondary" sx={{ mt: 1, mb: 3, minHeight: 72 }}>Monitor AI usage, model performance, OCR, RAG quality, and maintain demonstration accounts.</Typography>
            {adminSession
              ? <Button component={Link} to="/admin" variant="outlined" color="success" endIcon={<ArrowForwardRoundedIcon />} size="large">Continue to admin</Button>
              : accessConfig?.admin_auth_enabled
                ? <Button component={Link} to="/admin/login" variant="outlined" color="success" endIcon={<ArrowForwardRoundedIcon />} size="large">Admin sign in</Button>
                : <Button variant="outlined" color="success" endIcon={<ArrowForwardRoundedIcon />} size="large" onClick={() => void enterDemo('admin')} disabled={!accessConfig || opening !== null}>{opening === 'admin' ? 'Opening...' : 'Enter admin workspace'}</Button>}
          </CardContent>
        </Card>
      </Box>
      <Stack direction="row" spacing={1.5} alignItems="center" sx={{ color: 'text.secondary' }}>
        <DescriptionRoundedIcon fontSize="small" /><Typography variant="body2">Suppliers choose a category first, then complete details and upload documents.</Typography>
      </Stack>
    </Stack>
  )
}
