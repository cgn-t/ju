import { CssBaseline, ThemeProvider } from '@mui/material'
import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SnackbarProvider } from 'notistack'
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import NoTeamScreen from './components/NoTeamScreen'
import AppLayout from './layouts/AppLayout'
import Applications from './pages/Applications'
import CertMap from './pages/CertMap'
import Certificates from './pages/Certificates'
import Dashboard from './pages/Dashboard'
import Deployments from './pages/Deployments'
import DeploymentRunDetail from './pages/DeploymentRunDetail'
import DeploymentRunsAll from './pages/DeploymentRunsAll'
import Discovery from './pages/Discovery'
import Domains from './pages/Domains'
import Login from './pages/Login'
import Policy from './pages/Policy'
import Proposals from './pages/Proposals'
import Settings from './pages/Settings'
import { createAppTheme, type ThemeMode } from './theme'
import { usePageAccess } from './hooks/usePageAccess'

const queryClient: QueryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
  // HER başarılı mutation'dan sonra TÜM sorgular bayat işaretlenir: açık sayfadaki aktif
  // sorgular ANINDA arka planda yeniden çekilir, diğerleri bir sonraki görüntülenişte.
  // Önceden her mutation yalnız kendi bildiği queryKey'leri invalidate ediyordu; kaçan
  // bir bağımlılık (ör. dashboard/cert-map) staleTime (30 sn) boyunca bayat kalıyor ve
  // kullanıcı sayfayı ELLE yenilemek zorunda kalıyordu. Veri hacmi küçük olduğundan
  // toplu invalidation'ın maliyeti ihmal edilebilir; doğruluk garantisi tam.
  mutationCache: new MutationCache({
    onSuccess: () => { queryClient.invalidateQueries() },
  }),
})

const ThemeModeContext = createContext<{ mode: ThemeMode; toggle: () => void }>({
  mode: 'dark',
  toggle: () => {},
})

export const useThemeMode = () => useContext(ThemeModeContext)

function Protected() {
  const { token, hasNoTeam } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  // RBAC: giriş yaptı ama hiçbir takımda değil → içerik yok, boş-durum ekranı.
  if (hasNoTeam) return <NoTeamScreen />
  return <AppLayout />
}

// Uyum/Devir Önerisi/Keşif/Dağıtım: varsayılan admin+allviewer (+ Devir Önerisi'nde SY üyeleri
// kendi teklifleri için), Ayarlar>Erişim'den herkese açılabilir (bkz. security.page_visible).
// Yükleme bitmeden YÖNLENDİRME yapma — aksi halde admin'in doğrudan/refresh erişimi anlık "/"e
// sıçrar (auth-me henüz cache'e gelmeden isLoading=false sanılırsa yanlış-negatif redirect olur).
function PageAccessRoute({ page, children }: {
  page: 'policy' | 'proposals' | 'discovery' | 'deployments'; children: ReactNode
}) {
  const access = usePageAccess()
  if (access.isLoading) return null
  return access[page] ? <>{children}</> : <Navigate to="/" replace />
}

// /settings artık HERKESE açık: admin tüm sekmeleri, diğer kullanıcılar yalnız 'Etiketler'
// sekmesini görür (Settings.tsx içinde role göre daraltılır). Takımsız kullanıcıyı zaten
// Protected'daki hasNoTeam ekranı durduruyor.

export default function App() {
  const [mode, setMode] = useState<ThemeMode>(
    (localStorage.getItem('jumbo_theme') as ThemeMode) || 'light',
  )
  const theme = useMemo(() => createAppTheme(mode), [mode])
  const toggle = () => {
    const next: ThemeMode = mode === 'dark' ? 'light' : 'dark'
    localStorage.setItem('jumbo_theme', next)
    setMode(next)
  }

  return (
    <ThemeModeContext.Provider value={{ mode, toggle }}>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <QueryClientProvider client={queryClient}>
        <SnackbarProvider maxSnack={3} autoHideDuration={2500}
                          anchorOrigin={{ vertical: 'top', horizontal: 'center' }}>
          <AuthProvider>
            <BrowserRouter>
              <Routes>
                <Route path="/login" element={<Login />} />
                <Route element={<Protected />}>
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/certificates" element={<Certificates />} />
                  <Route path="/domains" element={<Domains />} />
                  <Route path="/proposals" element={<PageAccessRoute page="proposals"><Proposals /></PageAccessRoute>} />
                  <Route path="/cert-map" element={<CertMap />} />
                  <Route path="/applications" element={<Applications />} />
                  <Route path="/policy" element={<PageAccessRoute page="policy"><Policy /></PageAccessRoute>} />
                  <Route path="/discovery" element={<PageAccessRoute page="discovery"><Discovery /></PageAccessRoute>} />
                  <Route path="/deployments" element={<PageAccessRoute page="deployments"><Deployments /></PageAccessRoute>} />
                  <Route path="/deployments/runs" element={<PageAccessRoute page="deployments"><DeploymentRunsAll /></PageAccessRoute>} />
                  <Route path="/deployments/runs/:runId" element={<PageAccessRoute page="deployments"><DeploymentRunDetail /></PageAccessRoute>} />
                  <Route path="/settings" element={<Settings />} />
                </Route>
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </BrowserRouter>
          </AuthProvider>
        </SnackbarProvider>
      </QueryClientProvider>
    </ThemeProvider>
    </ThemeModeContext.Provider>
  )
}
