import AddBusinessRoundedIcon from '@mui/icons-material/AddBusinessRounded'
import DashboardRoundedIcon from '@mui/icons-material/DashboardRounded'
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded'
import { AppBar, Box, Button, Container, Stack, Toolbar, Typography } from '@mui/material'
import { Link, Outlet, useLocation } from 'react-router-dom'
import { SupplierAssistantPopover } from './SupplierAssistantPopover'

export function AppShell() {
  const location = useLocation()

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <AppBar position="static" color="inherit" elevation={0} sx={{ borderBottom: '1px solid', borderColor: 'divider' }}>
        <Container maxWidth="lg">
          <Toolbar disableGutters sx={{ minHeight: 68, gap: 2 }}>
            <Box sx={{ display: 'grid', placeItems: 'center', width: 38, height: 38, borderRadius: 2, bgcolor: 'tertiary.main', color: 'white' }}>
              <AutoAwesomeRoundedIcon fontSize="small" />
            </Box>
            <Typography variant="h6" sx={{ flexGrow: 1 }}>VendorLens</Typography>
            <Stack direction="row" spacing={1}>
              <Button component={Link} to="/" startIcon={<DashboardRoundedIcon />} variant={location.pathname === '/' ? 'contained' : 'text'}>
                Dashboard
              </Button>
              <Button component={Link} to="/suppliers/new" startIcon={<AddBusinessRoundedIcon />} variant={location.pathname === '/suppliers/new' ? 'contained' : 'outlined'}>
                New supplier
              </Button>
            </Stack>
          </Toolbar>
        </Container>
      </AppBar>
      <Container maxWidth="lg" component="main" sx={{ py: { xs: 3, md: 5 } }}>
        <Outlet />
      </Container>
      <SupplierAssistantPopover />
    </Box>
  )
}
