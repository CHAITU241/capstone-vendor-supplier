import { createTheme } from '@mui/material/styles'

export const brandColors = {
  primary: '#2563EB',
  secondary: '#14B8A6',
  tertiary: '#7C3AED',
  background: '#F8FAFC',
  surface: '#FFFFFF',
  error: '#DC2626',
  warning: '#D97706',
  textPrimary: '#0F172A',
  textSecondary: '#475569',
} as const

export const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: brandColors.primary },
    secondary: { main: brandColors.secondary },
    tertiary: { main: brandColors.tertiary },
    background: { default: brandColors.background, paper: brandColors.surface },
    error: { main: brandColors.error },
    warning: { main: brandColors.warning },
    text: { primary: brandColors.textPrimary, secondary: brandColors.textSecondary },
  },
  shape: { borderRadius: 12 },
  typography: {
    fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    h4: { fontWeight: 750, letterSpacing: '-0.03em' },
    h5: { fontWeight: 700, letterSpacing: '-0.02em' },
    h6: { fontWeight: 700 },
    button: { textTransform: 'none', fontWeight: 650 },
  },
  components: {
    MuiButton: { defaultProps: { disableElevation: true } },
    MuiCard: {
      styleOverrides: {
        root: { border: '1px solid #E2E8F0', boxShadow: '0 8px 24px rgba(15, 23, 42, 0.05)' },
      },
    },
  },
})

