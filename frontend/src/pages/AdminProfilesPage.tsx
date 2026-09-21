import ContentCopyRoundedIcon from '@mui/icons-material/ContentCopyRounded'
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded'
import { Alert, Box, Button, Card, CardContent, Chip, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Stack, TextField, Tooltip, Typography } from '@mui/material'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AdminProfile } from '../api/types'

export function AdminProfilesPage() {
  const [profiles, setProfiles] = useState<AdminProfile[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [password, setPassword] = useState<{ id: string; value: string } | null>(null)
  const [target, setTarget] = useState<AdminProfile | null>(null)
  const [confirmation, setConfirmation] = useState('')

  useEffect(() => { void api.adminProfiles().then(setProfiles).catch((err: Error) => setError(err.message)) }, [])

  async function copy(value: string, label: string) {
    try { await navigator.clipboard.writeText(value); setMessage(`${label} copied to clipboard.`) }
    catch { setError('Could not copy. Select the text and copy it manually.') }
  }

  async function reset(profile: AdminProfile) {
    setBusy(true); setError(''); setMessage(''); setPassword(null)
    try {
      const result = await api.adminResetPassword(profile.id)
      setPassword({ id: profile.id, value: result.password })
      setMessage('New password created. Copy it now; it will not be shown again. All supplier sessions were signed out.')
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not reset the password.') }
    finally { setBusy(false) }
  }

  async function remove() {
    if (!target || confirmation !== (target.email ?? target.name)) return
    setBusy(true); setError(''); setMessage('')
    try {
      await api.adminDeleteProfile(target.id)
      setProfiles((current) => current.filter((profile) => profile.id !== target.id))
      setPassword(null); setTarget(null); setConfirmation('')
      setMessage('Profile, account, uploads, and archived originals deleted.')
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not delete the profile.') }
    finally { setBusy(false) }
  }

  return <Stack spacing={3}>
    <Box><Typography variant="h4">Supplier profiles</Typography><Typography color="text.secondary">All applications, including drafts. Passwords cannot be viewed; resetting one generates a new password shown once.</Typography></Box>
    {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}
    {message && <Alert severity="info" onClose={() => setMessage('')}>{message}</Alert>}
    {profiles.length === 0 && <Typography color="text.secondary">No supplier profiles found.</Typography>}
    {profiles.map((profile) => <Card key={profile.id}><CardContent>
      <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2}>
        <Box sx={{ minWidth: 0 }}>
          <Stack direction="row" alignItems="center" gap={1}><Typography variant="h6">{profile.name}</Typography><Chip label={profile.submitted_at ? profile.status.replace('_', ' ') : 'Draft'} size="small" /></Stack>
          <Stack direction="row" alignItems="center" gap={0.5}>
            <Typography sx={{ wordBreak: 'break-all' }}>{profile.email ?? 'No login (reviewer-created)'}</Typography>
            {profile.email && <Tooltip title="Copy username"><IconButton size="small" aria-label={`Copy username for ${profile.email}`} onClick={() => void copy(profile.email!, 'Username')}><ContentCopyRoundedIcon fontSize="small" /></IconButton></Tooltip>}
          </Stack>
          <Typography variant="body2" color="text.secondary">{profile.document_count} current uploads · {profile.archived_count} previous uploads · Created {new Date(profile.created_at).toLocaleString()}</Typography>
        </Box>
        <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap">
          {profile.email && <Button size="small" disabled={busy} onClick={() => void reset(profile)}>Reset password</Button>}
          <Button size="small" color="error" startIcon={<DeleteOutlineRoundedIcon />} disabled={busy} onClick={() => { setTarget(profile); setConfirmation('') }}>Delete profile</Button>
        </Stack>
      </Stack>
      {password?.id === profile.id && <Alert severity="warning" sx={{ mt: 2 }} action={<Button size="small" onClick={() => void copy(password.value, 'Password')}>Copy password</Button>}>
        New password: <Box component="span" sx={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>{password.value}</Box>
      </Alert>}
    </CardContent></Card>)}
    <Dialog open={Boolean(target)} onClose={() => !busy && setTarget(null)} fullWidth maxWidth="sm">
      <DialogTitle>Delete supplier profile?</DialogTitle>
      <DialogContent>
        <Typography sx={{ mb: 2 }}>This permanently deletes the account, application, current and previous uploads, review records, and stored originals. Type <strong>{target?.email ?? target?.name}</strong> to confirm.</Typography>
        <TextField fullWidth label="Type the value above" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} />
      </DialogContent>
      <DialogActions><Button disabled={busy} onClick={() => setTarget(null)}>Cancel</Button><Button color="error" variant="contained" disabled={busy || confirmation !== (target?.email ?? target?.name)} onClick={() => void remove()}>Delete permanently</Button></DialogActions>
    </Dialog>
  </Stack>
}
