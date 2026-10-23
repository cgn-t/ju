import AccountTreeIcon from '@mui/icons-material/AccountTree'
import AppsIcon from '@mui/icons-material/Apps'
import AssignmentTurnedInIcon from '@mui/icons-material/AssignmentTurnedIn'
import DarkModeIcon from '@mui/icons-material/DarkMode'
import KeyboardDoubleArrowLeftIcon from '@mui/icons-material/KeyboardDoubleArrowLeft'
import KeyboardDoubleArrowRightIcon from '@mui/icons-material/KeyboardDoubleArrowRight'
import HistoryIcon from '@mui/icons-material/History'
import LanguageIcon from '@mui/icons-material/Language'
import LightModeIcon from '@mui/icons-material/LightMode'
import LogoutIcon from '@mui/icons-material/Logout'
import MenuIcon from '@mui/icons-material/Menu'
import PersonIcon from '@mui/icons-material/Person'
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch'
import RuleIcon from '@mui/icons-material/Rule'
import SettingsIcon from '@mui/icons-material/Settings'
import UnfoldMoreIcon from '@mui/icons-material/UnfoldMore'
import TravelExploreIcon from '@mui/icons-material/TravelExplore'
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser'
import {
  AppBar, Avatar, Badge, Box, ButtonBase, Chip, Container, Divider, Drawer, IconButton, List,
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
  const roleLabel = ROLE_LABELS[role ?? ''] ?? role ?? ''
  const initial = (fullName || username || '?')[0]?.toUpperCase()
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
      {/* Üst: logo + menüyü daralt/genişlet (masaüstü). Daraltılmışta düğme logonun altında. */}
      <Box sx={{ display: 'flex', flexDirection: compact ? 'column' : 'row', alignItems: 'center',
                 gap: compact ? 0.5 : 0, px: compact ? 1 : 2, pr: compact ? 1 : 1, py: compact ? 1.25 : 1.75 }}>
        <Box component={Link} to="/" onClick={() => setDrawerOpen(false)}
             sx={{ display: 'flex', alignItems: 'center', gap: 1.25, minWidth: 0, flexGrow: compact ? 0 : 1,
                   textDecoration: 'none', color: 'inherit', '&:hover': { opacity: 0.9 } }}>
          <Box component="img" src="/favicon.svg" alt="JUMBO" sx={{ width: 36, height: 36, display: 'block' }} />
          {!compact && (
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="h6" sx={{ lineHeight: 1.1 }}>JUMBO</Typography>
              <Typography variant="caption" noWrap component="div" sx={{ opacity: 0.8 }}>Sertifika Yönetimi</Typography>
            </Box>
          )}
        </Box>
        <Tooltip title={compact ? 'Menüyü genişlet' : 'Menüyü daralt'} placement="right">
          <IconButton size="small" onClick={toggleCollapsed}
                      aria-label={compact ? 'Menüyü genişlet' : 'Menüyü daralt'}
                      sx={{ display: { xs: 'none', md: 'inline-flex' }, color: 'rgba(255,255,255,0.75)',
                            '&:hover': { color: '#fff', bgcolor: 'rgba(255,255,255,0.08)' } }}>
            {compact ? <KeyboardDoubleArrowRightIcon fontSize="small" /> : <KeyboardDoubleArrowLeftIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
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
      {/* Kullanıcı: dikey menünün altında (tıklayınca tema / ayarlar / çıkış menüsü yukarı açılır) */}
      <Tooltip title={compact ? `${fullName || username} · ${roleLabel}` : ''} placement="right">
        <ButtonBase onClick={(e) => setAnchor(e.currentTarget)} aria-label="Kullanıcı menüsü"
                    sx={{ mx: 1.25, my: 1, px: compact ? 0.5 : 1, py: 0.75, borderRadius: '10px', gap: 1.25,
                          justifyContent: compact ? 'center' : 'flex-start', textAlign: 'left',
                          color: '#fff', transition: 'background-color 150ms',
                          '&:hover': { bgcolor: 'rgba(255,255,255,0.08)' } }}>
          <Avatar sx={{ width: 34, height: 34, bgcolor: 'rgba(255,255,255,0.16)', color: '#fff', fontSize: 15, fontWeight: 700 }}>
            {initial}
          </Avatar>
          {!compact && (
            <>
              {/* Uzun LDAP Ad Soyad'ı menüyü bozmasın: tek satır + kısaltma (…) */}
              <Box sx={{ minWidth: 0, flexGrow: 1 }}>
                <Typography variant="body2" noWrap title={fullName || username || undefined}
                            sx={{ fontWeight: 700, lineHeight: 1.3 }}>{fullName || username}</Typography>
                <Typography variant="caption" noWrap component="div"
                            sx={{ color: 'rgba(255,255,255,0.65)', lineHeight: 1.3 }}>{roleLabel}</Typography>
              </Box>
              <UnfoldMoreIcon fontSize="small" sx={{ color: 'rgba(255,255,255,0.6)' }} />
            </>
          )}
        </ButtonBase>
      </Tooltip>
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
      {/* Üst çubuk yalnız mobilde (xs/sm): menü düğmesi + logo. Masaüstünde sol menü yeterli. */}
      <AppBar position="sticky" elevation={0} color="inherit"
              sx={{ display: { xs: 'block', md: 'none' }, bgcolor: 'background.paper', backgroundImage: 'none',
                    borderBottom: 1, borderColor: 'divider' }}>
        <Toolbar variant="dense" sx={{ gap: 1, minHeight: 56 }}>
          <IconButton color="inherit" edge="start" aria-label="Menüyü aç" onClick={() => setDrawerOpen(true)}>
            <MenuIcon />
          </IconButton>
          <Typography variant="h6" sx={{ fontSize: 17 }}>JUMBO</Typography>
        </Toolbar>
      </AppBar>
      <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}
            anchorOrigin={{ vertical: 'top', horizontal: 'left' }}
            transformOrigin={{ vertical: 'bottom', horizontal: 'left' }}
            slotProps={{ paper: { sx: { width: 280, mt: -1 } } }}>
        <Box sx={{ px: 2, py: 1.5, display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Avatar sx={{ bgcolor: 'primary.main' }}>{initial}</Avatar>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="subtitle2" noWrap>{fullName || username}</Typography>
            {email && <Typography variant="caption" color="text.secondary" noWrap sx={{ display: 'block' }}>{email}</Typography>}
            <Chip size="small" label={roleLabel} sx={{ mt: 0.5 }} />
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

        <MenuItem onClick={() => { setAnchor(null); setDrawerOpen(false); navigate('/profile') }}>
          <ListItemIcon><PersonIcon fontSize="small" /></ListItemIcon>
          <ListItemText>Profilim</ListItemText>
        </MenuItem>
        {/* Ayarlar HERKESE görünür: admin tüm sekmeleri, diğerleri yalnız Etiketler'i görür */}
        <MenuItem onClick={() => { setAnchor(null); setDrawerOpen(false); navigate('/settings') }}>
          <ListItemIcon><SettingsIcon fontSize="small" /></ListItemIcon>
          <ListItemText>{isAdmin ? 'Ayarlar' : 'Etiketler'}</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => { setAnchor(null); logout(); navigate('/login') }}>
          <ListItemIcon><LogoutIcon fontSize="small" /></ListItemIcon>
          <ListItemText>Çıkış Yap</ListItemText>
        </MenuItem>
      </Menu>

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
