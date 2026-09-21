import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded'
import { Alert, Button, Card, CardContent, Stack, TextField, Typography } from '@mui/material'
import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'

export function AdminLoginPage() {
  const { session, setSession } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  if (session?.role === 'admin') return <Navigate to="/admin" replace />

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      setSession(await api.adminLogin(email.trim(), password))
      navigate('/admin')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not sign in.')
    } finally { setBusy(false) }
  }

  return <Stack spacing={3} maxWidth={480} mx="auto">
    <Button component={Link} to="/supplier/login" startIcon={<ArrowBackRoundedIcon />} sx={{ alignSelf: 'flex-start' }}>Back</Button>
    <Typography variant="h5">Admin sign in</Typography>
    <Card><CardContent sx={{ p: 4 }}>
      <Stack component="form" spacing={2.5} onSubmit={(event) => void signIn(event)}>
        {error && <Alert severity="error">{error}</Alert>}
        <TextField required label="Admin email" type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} />
        <TextField required label="Password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
        <Button type="submit" variant="contained" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</Button>
      </Stack>
    </CardContent></Card>
  </Stack>
}
