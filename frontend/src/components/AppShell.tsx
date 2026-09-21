import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded'
import LogoutRoundedIcon from '@mui/icons-material/LogoutRounded'
import { AppBar, Box, Button, Container, Stack, Toolbar, Typography } from '@mui/material'
import { Link, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { SupplierAssistantPopover } from './SupplierAssistantPopover'

export function AppShell() {
  const { session, signOut } = useAuth()
  const navigate = useNavigate()
  const workspace = session?.role === 'reviewer' ? '/review' : session?.role === 'admin' ? '/admin' : '/supplier/application'

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <AppBar position="static" color="inherit" elevation={0} sx={{ borderBottom: '1px solid', borderColor: 'divider' }}>
        <Container maxWidth="lg">
          <Toolbar disableGutters sx={{ minHeight: 72, gap: 2 }}>
            <Box component={Link} to="/" sx={{ display: 'flex', alignItems: 'center', gap: 1.5, textDecoration: 'none', color: 'text.primary', flexGrow: 1 }}>
            <Box sx={{ display: 'grid', placeItems: 'center', width: 38, height: 38, borderRadius: 2, bgcolor: 'tertiary.main', color: 'white' }}>
              <AutoAwesomeRoundedIcon fontSize="small" />
            </Box>
            <Typography variant="h6">VendorLens</Typography>
            </Box>
            {session && <Stack direction="row" spacing={1} alignItems="center">
              <Button component={Link} to={workspace} variant="text">{session.role === 'reviewer' ? 'Review workspace' : session.role === 'admin' ? 'Admin' : 'My application'}</Button>
              <Button onClick={() => { void signOut().then(() => navigate('/')) }} startIcon={<LogoutRoundedIcon />} color="inherit" sx={{ display: { xs: 'none', sm: 'inline-flex' } }}>Sign out</Button>
              <Button onClick={() => { void signOut().then(() => navigate('/')) }} color="inherit" sx={{ display: { xs: 'inline-flex', sm: 'none' } }}>Exit</Button>
            </Stack>}
          </Toolbar>
        </Container>
      </AppBar>
      <Container maxWidth="lg" component="main" sx={{ py: { xs: 4, md: 6 }, pb: 12 }}>
        <Outlet />
      </Container>
      <SupplierAssistantPopover />
    </Box>
  )
}
