import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded'
import { Alert, Box, Button, Card, CardContent, Stack, TextField, Typography } from '@mui/material'
import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'

export function SupplierLoginPage() {
  const { session, setSession } = useAuth()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [mode, setMode] = useState<'login' | 'register'>(() => searchParams.get('mode') === 'login' ? 'login' : 'register')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  if (session?.role === 'supplier') return <Navigate to="/supplier/application" replace />

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      setSession(mode === 'register' ? await api.register(email.trim(), password) : await api.login(email.trim(), password))
      navigate('/supplier/application')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not sign in.')
    } finally { setBusy(false) }
  }

  return <Stack spacing={3} maxWidth={520} mx="auto">
    <Button component={Link} to="/" startIcon={<ArrowBackRoundedIcon />} sx={{ alignSelf: 'flex-start' }}>Back to home</Button>
    <Box><Typography variant="h4">{mode === 'register' ? 'Start your application' : 'Welcome back'}</Typography>
      <Typography color="text.secondary" sx={{ mt: 1 }}>Use your email and password to save your progress and return later.</Typography></Box>
    <Card><CardContent sx={{ p: { xs: 3, md: 4 }, '&:last-child': { pb: 4 } }}>
      <Stack component="form" spacing={2.5} onSubmit={(event) => void handleSubmit(event)}>
        {error && <Alert severity="error">{error}</Alert>}
        {session?.role === 'reviewer' && <Alert severity="info">Signing in as a supplier will switch workspaces.</Alert>}
        <TextField required autoComplete="email" type="email" label="Work email" value={email} onChange={(event) => setEmail(event.target.value)} />
        <TextField required type="password" autoComplete={mode === 'register' ? 'new-password' : 'current-password'} label="Password" value={password} onChange={(event) => setPassword(event.target.value)} inputProps={{ minLength: 8, maxLength: 128 }} helperText={mode === 'register' ? 'At least 8 characters.' : undefined} />
        <Button type="submit" variant="contained" size="large" disabled={busy}>{busy ? 'Please wait...' : mode === 'register' ? 'Create account and continue' : 'Sign in and continue'}</Button>
        <Button onClick={() => {
          const nextMode = mode === 'register' ? 'login' : 'register'
          setMode(nextMode)
          setSearchParams({ mode: nextMode }, { replace: true })
          setError('')
        }}>
          {mode === 'register' ? 'Already started? Sign in' : 'New supplier? Create an account'}
        </Button>
      </Stack>
    </CardContent></Card>
    <Button component={Link} to="/admin/login" size="small" color="inherit" sx={{ alignSelf: 'flex-end', color: 'text.disabled', fontSize: 12 }}>Admin</Button>
  </Stack>
}
