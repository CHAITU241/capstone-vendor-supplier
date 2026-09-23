import AnalyticsRoundedIcon from '@mui/icons-material/AnalyticsRounded'
import ManageAccountsRoundedIcon from '@mui/icons-material/ManageAccountsRounded'
import { Box, Stack, Tab, Tabs, Typography } from '@mui/material'
import { useState } from 'react'
import { AdminObservabilityPanel } from './AdminObservabilityPanel'
import { AdminProfilesPage } from './AdminProfilesPage'

export function AdminDashboardPage() {
  const [section, setSection] = useState<'observability' | 'profiles'>('observability')

  return <Stack spacing={3}>
    <Box>
      <Typography variant="h4">Admin portal</Typography>
      <Typography color="text.secondary" sx={{ mt: .75 }}>Monitor AI operations and maintain demonstration supplier accounts.</Typography>
    </Box>
    <Tabs value={section} onChange={(_, value: 'observability' | 'profiles') => setSection(value)} aria-label="Admin portal sections">
      <Tab value="observability" icon={<AnalyticsRoundedIcon />} iconPosition="start" label="AI observability" />
      <Tab value="profiles" icon={<ManageAccountsRoundedIcon />} iconPosition="start" label="Supplier profiles" />
    </Tabs>
    {section === 'observability' ? <AdminObservabilityPanel /> : <AdminProfilesPage />}
  </Stack>
}
