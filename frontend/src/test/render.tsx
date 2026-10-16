import { CssBaseline, ThemeProvider } from '@mui/material'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { SnackbarProvider } from 'notistack'
import type { ReactElement } from 'react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { createAppTheme } from '../theme'

type Role = 'admin' | 'editor' | 'viewer' | 'allviewer'

/** Sayfayı uygulamadaki sağlayıcılarla (tema, react-query, snackbar, auth, router) render eder.
 *  Rol, AuthProvider'ın okuduğu localStorage üzerinden verilir. */
export function renderPage(ui: ReactElement, { role = 'admin', url = '/' }: { role?: Role; url?: string } = {}) {
  localStorage.setItem('jumbo_token', 'test-token')
  localStorage.setItem('jumbo_username', 'tester')
  localStorage.setItem('jumbo_role', role)
  window.history.replaceState(null, '', url)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <ThemeProvider theme={createAppTheme('light')}>
      <CssBaseline />
      <QueryClientProvider client={queryClient}>
        <SnackbarProvider>
          <AuthProvider>
            <BrowserRouter>{ui}</BrowserRouter>
          </AuthProvider>
        </SnackbarProvider>
      </QueryClientProvider>
    </ThemeProvider>,
  )
}
