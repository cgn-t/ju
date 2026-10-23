import AccountTreeIcon from '@mui/icons-material/AccountTree'
import AppsIcon from '@mui/icons-material/Apps'
import AssignmentTurnedInIcon from '@mui/icons-material/AssignmentTurnedIn'
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import DarkModeIcon from '@mui/icons-material/DarkMode'
import HistoryIcon from '@mui/icons-material/History'
import LanguageIcon from '@mui/icons-material/Language'
import LightModeIcon from '@mui/icons-material/LightMode'
import LogoutIcon from '@mui/icons-material/Logout'
import MenuIcon from '@mui/icons-material/Menu'
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch'
import RuleIcon from '@mui/icons-material/Rule'
import SettingsIcon from '@mui/icons-material/Settings'
import TravelExploreIcon from '@mui/icons-material/TravelExplore'
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser'
import {
  AppBar, Avatar, Badge, Box, Button, Chip, Container, Divider, Drawer, IconButton, List,
  ListItemButton, ListItemIcon, ListItemText, ListSubheader, Menu, MenuItem, Switch, Toolbar,
  Tooltip, Typography,
} from '@mui/material'
import { Fragment, useState, type ComponentType } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useThemeMode } from '../App'
import { useAuth } from '../auth/AuthContext'
import { usePageAccess } from '../hooks/usePageAccess'
import { useDiscoveredCount } from '../pages/Discovery'
import { usePolicyViolationCount } from '../pages/Policy'
import { usePendingProposalCount } from '../pages/Proposals'

// Sol menü: sık kullanılanlar tekil; kalanı 'Analiz' ve 'İşlemler' başlıkları altında gruplanır.
type NavLink = { to: string; label: string }
type NavGroup = { label: string; items: NavLink[] }
type NavEntry = NavLink | NavGroup
const isGroup = (e: NavEntry): e is NavGroup => 'items' in e

const NAV: NavEntry[] = [
  { to: '/certificates', label: 'SSL Sertifikaları' },
  { to: '/domains', label: 'Domainler' },
  { to: '/applications', label: 'Uygulamalar' },
  { label: 'Analiz', items: [
    { to: '/cert-map', label: 'Sertifika Haritası' },
    { to: '/policy', label: 'Uyum' },
    { to: '/discovery', label: 'Keşif' },
  ] },
  { label: 'İşlemler', items: [
    { to: '/proposals', label: 'Değişiklik Talepleri' },
    { to: '/deployments', label: 'Dağıtım' },
    { to: '/deployments/runs', label: 'Tüm Çalıştırmalar' },
  ] },
]

const NAV_ICONS: Record<string, ComponentType<{ fontSize?: 'small' }>> = {
  '/certificates': VerifiedUserIcon, '/domains': LanguageIcon, '/applications': AppsIcon,
  '/cert-map': AccountTreeIcon, '/policy': RuleIcon, '/discovery': TravelExploreIcon,
  '/proposals': AssignmentTurnedInIcon, '/deployments': RocketLaunchIcon, '/deployments/runs': HistoryIcon,
}
const NAV_W = 248
const NAV_W_COMPACT = 68
const COLLAPSE_KEY = 'jumbo.nav.collapsed'

function readCollapsed() {
  try { return localStorage.getItem(COLLAPSE_KEY) === '1' } catch { return false }
}

// Sayfa-görünürlük ayarına tabi rotalar → usePageAccess() anahtarı (bkz. security.page_visible)
const PAGE_FOR_PATH: Record<string, 'policy' | 'proposals' | 'discovery' | 'deployments'> = {
  '/policy': 'policy', '/proposals': 'proposals', '/discovery': 'discovery',
  '/deployments': 'deployments', '/deployments/runs': 'deployments',
}

const ROLE_LABELS: Record<string, string> = {
  admin: 'Yönetici', editor: 'SY Ekip', viewer: 'İzleyici', none: 'Yetkisiz',
}

export default function AppLayout() {
  const { username, fullName, role, email, logout, isAdmin } = useAuth()
  const { mode, toggle } = useThemeMode()
  const location = useLocation()
  const navigate = useNavigate()
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)   // mobil (xs) navigasyon çekmecesi
  const [collapsed, setCollapsed] = useState(readCollapsed)  // masaüstü sol menü daraltılmış mı (tarayıcıda hatırlanır)
  const toggleCollapsed = () => setCollapsed((c) => {
    try { localStorage.setItem(COLLAPSE_KEY, c ? '0' : '1') } catch { /* gizli pencere: yalnız bu oturum */ }
    return !c
  })
  const access = usePageAccess()
  const pendingCount = usePendingProposalCount()
  const shadowCount = useDiscoveredCount()
  const violationCount = usePolicyViolationCount()

  const isActive = (to: string) => location.pathname === to
  const badgeFor = (to: string) =>
    to === '/proposals' ? pendingCount
      : to === '/discovery' ? shadowCount
        : to === '/policy' ? violationCount : 0
  // Menüde erişimi olmayan rotaları gizle (bkz. usePageAccess `nav` — SY üyeliği carve-out'u
  // burada UYGULANMAZ; rota erişimi/onay iş akışı bundan etkilenmez). Boşalan gruplar düşer.
  const canSee = (to: string) => { const page = PAGE_FOR_PATH[to]; return !page || access.nav[page] }
  const navEntries: NavEntry[] = NAV
    .map((e) => (isGroup(e) ? { ...e, items: e.items.filter((i) => canSee(i.to)) } : e))
    .filter((e) => (isGroup(e) ? e.items.length > 0 : canSee(e.to)))

  // Sol menü içeriği: masaüstünde kalıcı kenar çubuğu, mobilde (xs) açılır çekmece olarak kullanılır.
  // `compact` = daraltılmış masaüstü görünümü (yalnız simgeler; ad tooltip'te).
  const navItem = (item: NavLink, compact: boolean, nested = false) => {
    const Icon = NAV_ICONS[item.to]
    const badge = badgeFor(item.to)
    const button = (
      <ListItemButton key={item.to} component={Link} to={item.to} selected={isActive(item.to)}
                      onClick={() => setDrawerOpen(false)}
                      sx={{ mx: 1.25, my: 0.25, borderRadius: '10px', minHeight: 40, position: 'relative',
                            pl: compact ? 1.5 : nested ? 1.75 : 1.5, pr: compact ? 1.5 : 1,
                            justifyContent: compact ? 'center' : 'flex-start',
                            color: 'rgba(255,255,255,0.74)', transition: 'background-color 150ms, color 150ms',
                            '&:hover': { bgcolor: 'rgba(255,255,255,0.08)', color: '#fff' },
                            '&.Mui-selected, &.Mui-selected:hover': { bgcolor: 'rgba(255,255,255,0.14)', color: '#fff',
                                                                     boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.10)' },
                            '&.Mui-selected::before': { content: '""', position: 'absolute', left: -10, top: 9, bottom: 9,
                                                        width: 3, borderRadius: 2, bgcolor: '#fff' } }}>
        <ListItemIcon sx={{ minWidth: compact ? 0 : 36, color: 'inherit' }}>
          <Badge color="warning" badgeContent={compact ? badge : 0} max={99}>
            {Icon ? <Icon fontSize="small" /> : null}
          </Badge>
        </ListItemIcon>
        {!compact && (
          <>
            <ListItemText primary={item.label}
                          slotProps={{ primary: { noWrap: true, sx: { fontSize: 14, fontWeight: isActive(item.to) ? 700 : 500 } } }} />
            {badge > 0 && <Chip size="small" color="warning" label={badge} sx={{ height: 20 }} />}
          </>
        )}
      </ListItemButton>
    )
    return compact ? <Tooltip key={item.to} title={item.label} placement="right">{button}</Tooltip> : button
  }

  const navContent = (compact: boolean) => (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', color: '#fff',
               background: 'linear-gradient(180deg, #7e1a1f 0%, #5e1317 100%)' }}>
      <Box component={Link} to="/" onClick={() => setDrawerOpen(false)}
           sx={{ display: 'flex', alignItems: 'center', gap: 1.25, px: compact ? 1.5 : 2, py: 1.75,
                 justifyContent: compact ? 'center' : 'flex-start',
                 textDecoration: 'none', color: 'inherit', '&:hover': { opacity: 0.9 } }}>
        <Box component="img" src="/favicon.svg" alt="JUMBO" sx={{ width: 36, height: 36, display: 'block' }} />
        {!compact && (
          <Box>
            <Typography variant="h6" sx={{ lineHeight: 1.1 }}>JUMBO</Typography>
            <Typography variant="caption" sx={{ opacity: 0.8 }}>Sertifika Yönetimi</Typography>
          </Box>
        )}
      </Box>
      <Divider sx={{ borderColor: 'rgba(255,255,255,0.10)' }} />
      <List sx={{ py: 1, flexGrow: 1, overflowY: 'auto', overflowX: 'hidden' }}>
        {navEntries.map((entry) => (isGroup(entry) ? (
          <Fragment key={entry.label}>
            {compact ? (
              <Divider sx={{ my: 1, mx: 1.5, borderColor: 'rgba(255,255,255,0.15)' }} />
            ) : (
              <ListSubheader sx={{ bgcolor: 'transparent', color: 'rgba(255,255,255,0.5)', lineHeight: '30px', mt: 1.5, pl: 2.75,
                                   fontSize: 11, fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase' }}>
                {entry.label}
              </ListSubheader>
            )}
            {entry.items.map((item) => navItem(item, compact, true))}
          </Fragment>
        ) : navItem(entry, compact)))}
      </List>
      <Divider sx={{ borderColor: 'rgba(255,255,255,0.10)' }} />
      <Box sx={{ display: { xs: 'none', md: 'flex' }, justifyContent: compact ? 'center' : 'flex-end', p: 0.5 }}>
        <Tooltip title={compact ? 'Menüyü genişlet' : 'Menüyü daralt'} placement="right">
          <IconButton size="small" sx={{ color: 'rgba(255,255,255,0.8)' }} onClick={toggleCollapsed}
                      aria-label={compact ? 'Menüyü genişlet' : 'Menüyü daralt'}>
            {compact ? <ChevronRightIcon /> : <ChevronLeftIcon />}
          </IconButton>
        </Tooltip>
      </Box>
    </Box>
  )

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default', display: 'flex' }}>
      {/* Masaüstü (md+): kalıcı sol menü. Sayfa kaydırılsa da yerinde durur. */}
      <Box component="nav" aria-label="Ana menü"
           sx={{ display: { xs: 'none', md: 'block' }, width: collapsed ? NAV_W_COMPACT : NAV_W,
                 flexShrink: 0, position: 'sticky', top: 0, height: '100vh',
                 transition: 'width 150ms ease' }}>
        {navContent(collapsed)}
      </Box>

      <Box sx={{ flexGrow: 1, minWidth: 0 }}>
      <AppBar position="sticky" elevation={0} color="inherit"
              sx={{ bgcolor: 'background.paper', backgroundImage: 'none', borderBottom: 1, borderColor: 'divider' }}>
        <Toolbar variant="dense" sx={{ gap: 1, minHeight: 56 }}>
          {/* Mobilde (xs) menü hamburger'ı; md+ gizli (sol menü zaten görünür). */}
          <IconButton color="inherit" edge="start" aria-label="Menüyü aç"
                      onClick={() => setDrawerOpen(true)}
                      sx={{ display: { xs: 'inline-flex', md: 'none' } }}>
            <MenuIcon />
          </IconButton>
          <Box sx={{ flexGrow: 1 }} />
          <Button color="inherit" onClick={(e) => setAnchor(e.currentTarget)} sx={{ textTransform: 'none', minWidth: 0 }}>
            <Avatar sx={{ width: 32, height: 32, mr: { xs: 0, sm: 1 }, bgcolor: '#8f1d22', color: '#fff' }}>
              {(fullName || username || '?')[0]?.toUpperCase()}
            </Avatar>
            {/* Uzun LDAP Ad Soyad'ı üst çubuğu bozmasın: tek satır + kısaltma (…); xs'te yalnız avatar. */}
            <Box sx={{ textAlign: 'left', minWidth: 0, maxWidth: { xs: 110, sm: 200 }, display: { xs: 'none', sm: 'block' } }}>
              <Typography variant="body2" noWrap title={fullName || username || undefined}
                          sx={{ fontWeight: 700 }}>{fullName || username}</Typography>
              <Typography variant="caption" noWrap color="text.secondary"
                          sx={{ display: 'block' }}>{ROLE_LABELS[role ?? ''] ?? role}</Typography>
            </Box>
          </Button>
          <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}
                slotProps={{ paper: { sx: { width: 280, mt: 1 } } }}>
            <Box sx={{ px: 2, py: 1.5, display: 'flex', alignItems: 'center', gap: 1.5 }}>
              <Avatar sx={{ bgcolor: 'primary.main' }}>{(fullName || username || '?')[0]?.toUpperCase()}</Avatar>
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="subtitle2" noWrap>{fullName || username}</Typography>
                {email && <Typography variant="caption" color="text.secondary" noWrap sx={{ display: 'block' }}>{email}</Typography>}
                <Chip size="small" label={ROLE_LABELS[role ?? ''] ?? role} sx={{ mt: 0.5 }} />
              </Box>
            </Box>
            <Divider />

            <Typography variant="overline" sx={{ px: 2, pt: 1, display: 'block', color: 'text.secondary' }}>
              Görünüm
            </Typography>
            <MenuItem disableRipple sx={{ cursor: 'default', '&:hover': { bgcolor: 'transparent' } }}>
              <ListItemIcon>{mode === 'dark' ? <DarkModeIcon fontSize="small" /> : <LightModeIcon fontSize="small" />}</ListItemIcon>
              <ListItemText>Koyu tema</ListItemText>
              <Switch edge="end" checked={mode === 'dark'} onChange={toggle} />
            </MenuItem>
            <Divider />

            {/* Ayarlar HERKESE görünür: admin tüm sekmeleri, diğerleri yalnız Etiketler'i görür */}
            <MenuItem onClick={() => { setAnchor(null); navigate('/settings') }}>
              <ListItemIcon><SettingsIcon fontSize="small" /></ListItemIcon>
              <ListItemText>{isAdmin ? 'Ayarlar' : 'Etiketler'}</ListItemText>
            </MenuItem>
            <MenuItem onClick={() => { setAnchor(null); logout(); navigate('/login') }}>
              <ListItemIcon><LogoutIcon fontSize="small" /></ListItemIcon>
              <ListItemText>Çıkış Yap</ListItemText>
            </MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>

      {/* Mobil navigasyon çekmecesi (xs): aynı sol menü, tam genişlikte. */}
      <Drawer anchor="left" open={drawerOpen} onClose={() => setDrawerOpen(false)}
              ModalProps={{ keepMounted: true }} sx={{ display: { md: 'none' } }}>
        <Box sx={{ width: NAV_W, height: '100%' }} role="presentation">
          {navContent(false)}
        </Box>
      </Drawer>

      <Container maxWidth={false} sx={{ py: 3 }}>
        <Outlet />
      </Container>
      </Box>
    </Box>
  )
}
