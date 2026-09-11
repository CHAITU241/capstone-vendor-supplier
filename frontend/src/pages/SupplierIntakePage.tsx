import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded'
import { Alert, Box, Button, Card, CardContent, MenuItem, Stack, TextField, Typography } from '@mui/material'
import { FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { countries } from '../config/countries'

export function SupplierIntakePage() {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [country, setCountry] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSaving(true)
    try {
      const supplier = await api.createSupplier({
        name: name.trim(),
        country,
        contact_email: email.trim() || undefined,
      })
      navigate(`/suppliers/${supplier.id}`)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Supplier creation failed.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Stack spacing={3} maxWidth={720}>
      <Button component={Link} to="/" startIcon={<ArrowBackRoundedIcon />} sx={{ alignSelf: 'flex-start' }}>Back to dashboard</Button>
      <Box>
        <Typography variant="h4">Create supplier case</Typography>
        <Typography color="text.secondary" sx={{ mt: 0.75 }}>Start with basic details, then upload the required documents.</Typography>
      </Box>
      <Card><CardContent sx={{ p: { xs: 3, md: 4 } }}>
        <Stack component="form" spacing={3} onSubmit={handleSubmit}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField required label="Supplier name" value={name} onChange={(event) => setName(event.target.value)} inputProps={{ maxLength: 200 }} />
          <TextField select required label="Country" value={country} onChange={(event) => setCountry(event.target.value)}>
            <MenuItem value="" disabled>Select a country</MenuItem>
            {countries.map((countryName) => <MenuItem key={countryName} value={countryName}>{countryName}</MenuItem>)}
          </TextField>
          <TextField type="email" label="Contact email" value={email} onChange={(event) => setEmail(event.target.value)} />
          <Button type="submit" variant="contained" size="large" disabled={saving || name.trim().length < 2 || !country}>
            {saving ? 'Creating...' : 'Create and upload documents'}
          </Button>
        </Stack>
      </CardContent></Card>
    </Stack>
  )
}
