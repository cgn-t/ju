import AccountTreeIcon from '@mui/icons-material/AccountTree'
import AppsIcon from '@mui/icons-material/Apps'
import AssignmentTurnedInIcon from '@mui/icons-material/AssignmentTurnedIn'
import DarkModeIcon from '@mui/icons-material/DarkMode'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import KeyboardDoubleArrowLeftIcon from '@mui/icons-material/KeyboardDoubleArrowLeft'
import KeyboardDoubleArrowRightIcon from '@mui/icons-material/KeyboardDoubleArrowRight'
import GroupsIcon from '@mui/icons-material/Groups'
import HistoryIcon from '@mui/icons-material/History'
import MonitorHeartIcon from '@mui/icons-material/MonitorHeart'
import LanguageIcon from '@mui/icons-material/Language'
import LightModeIcon from '@mui/icons-material/LightMode'
import LogoutIcon from '@mui/icons-material/Logout'
import MenuIcon from '@mui/icons-material/Menu'
import MenuBookIcon from '@mui/icons-material/MenuBook'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import PersonIcon from '@mui/icons-material/Person'
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch'
import RuleIcon from '@mui/icons-material/Rule'
import SettingsIcon from '@mui/icons-material/Settings'
import UnfoldMoreIcon from '@mui/icons-material/UnfoldMore'
import TravelExploreIcon from '@mui/icons-material/TravelExplore'
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser'
import {
  AppBar, Avatar, Badge, Box, ButtonBase, Chip, Collapse, Container, Divider, Drawer, IconButton, List,
  ListItemButton, ListItemIcon, ListItemText, ListSubheader, Menu, MenuItem, Switch, Toolbar,
  Tooltip, Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { Fragment, useState, type ComponentType } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAiStatus } from '../hooks/useAiStatus'
import type { DirectoryProfile } from '../api/types'
import { useThemeMode } from '../App'
import { useAuth } from '../auth/AuthContext'
import { BRAND_GRADIENT } from '../theme'
import AiAssistant from '../components/AiAssistant'
import { usePageAccess } from '../hooks/usePageAccess'
import { useDiscoveredCount } from '../pages/Discovery'
import { usePolicyViolationCount } from '../pages/Policy'
import { usePendingProposalCount } from '../pages/Proposals'

// Sol menü: sık kullanılanlar tekil; kalanı 'Analiz' ve 'İşlemler' başlıkları altında gruplanır.
// 'Yardım > Kullanım Kılavuzu' yalnız Ayarlar > AI Asistanı'nda kurum wiki'si tanımlıysa görünür ve
// wiki sayfasını yeni sekmede açar (href).
type NavLink = { to: string; label: string; href?: string }
type NavGroup = { label: string; items: NavLink[] }
type NavEntry = NavLink | NavGroup
const isGroup = (e: NavEntry): e is NavGroup => 'items' in e

const NAV: NavEntry[] = [
  { to: '/overview', label: 'Genel Durum' },
  { to: '/my-team', label: 'Ekibim' },
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
    { to: '/system-health', label: 'Sistem Sağlığı' },
  ] },
]

const NAV_ICONS: Record<string, ComponentType<{ fontSize?: 'small' }>> = {
  '/certificates': VerifiedUserIcon, '/domains': LanguageIcon, '/applications': AppsIcon,
  '/cert-map': AccountTreeIcon, '/policy': RuleIcon, '/discovery': TravelExploreIcon,
  '/proposals': AssignmentTurnedInIcon, '/deployments': RocketLaunchIcon, '/deployments/runs': HistoryIcon,
  '/overview': GroupsIcon, '/my-team': GroupsIcon, '/system-health': MonitorHeartIcon, '/guide': MenuBookIcon,
}

// Rol kapılı rotalar: Genel Durum admin + Genel İzleyici, Ekibim editör + Ekip İzleyici, Sistem Sağlığı yalnız admin.
const ROLE_PATHS: Record<string, string[]> = {
  '/overview': ['admin', 'allviewer'],
  '/my-team': ['editor', 'viewer'],
  '/system-health': ['admin'],
}
const NAV_W = 248
const NAV_W_COMPACT = 68
const COLLAPSE_KEY = 'jumbo.nav.collapsed'
const CLOSED_GROUPS_KEY = 'jumbo.nav.closedGroups'   // kapatılan menü başlıkları (Analiz, İşlemler, Yardım)

function readCollapsed() {
  try { return localStorage.getItem(COLLAPSE_KEY) === '1' } catch { return false }
}

function readClosedGroups(): string[] {
  try { return JSON.parse(localStorage.getItem(CLOSED_GROUPS_KEY) ?? '[]') } catch { return [] }
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
  const { username, fullName, role, email, logout, isAdmin, photo: authPhoto, teamGroups: authTeams } = useAuth()
  const { mode, toggle } = useThemeMode()
  const location = useLocation()
  const navigate = useNavigate()
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)   // mobil (xs) navigasyon çekmecesi
  const [collapsed, setCollapsed] = useState(readCollapsed)  // masaüstü sol menü daraltılmış mı (tarayıcıda hatırlanır)
  const [aiDock, setAiDock] = useState(0)   // AI paneli açık ve sayfayı itiyorsa sağda bırakılan boşluk (px)
  // Menü başlıkları tıklanınca açılıp kapanır; seçim tarayıcıda hatırlanır (varsayılan: hepsi açık)
  const [closedGroups, setClosedGroups] = useState(readClosedGroups)
  const toggleGroup = (label: string) => setClosedGroups((g) => {
    const next = g.includes(label) ? g.filter((x) => x !== label) : [...g, label]
    try { localStorage.setItem(CLOSED_GROUPS_KEY, JSON.stringify(next)) } catch { /* gizli pencere: yalnız bu oturum */ }
    return next
  })
  const toggleCollapsed = () => setCollapsed((c) => {
    try { localStorage.setItem(COLLAPSE_KEY, c ? '0' : '1') } catch { /* gizli pencere: yalnız bu oturum */ }
    return !c
  })
  const roleLabel = ROLE_LABELS[role ?? ''] ?? role ?? ''
  // AD fotoğrafı ve ekip grubu (ör. SY-BBB) girişte gelir ve saklanır → beklemeden görünür. Bu sürümden
  // önce giriş yapmış oturumlarda yoksa Profilim'in sorgusundan bir kez alınır.
  const { data: dir } = useQuery<DirectoryProfile>({
    queryKey: ['directory', 'me'],
    queryFn: async () => (await api.get('/auth/me/directory')).data,
    staleTime: Infinity,
    retry: false,
    enabled: !authPhoto && !authTeams.length,
  })
  const photo = authPhoto || dir?.photo || undefined
  const teams = authTeams.length ? authTeams : (dir?.team_groups ?? [])
  const subLabel = teams.length ? teams.join(', ') : roleLabel
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
  const canSee = (to: string) => {
    if (ROLE_PATHS[to] && !ROLE_PATHS[to].includes(role ?? '')) return false
    const page = PAGE_FOR_PATH[to]
    return !page || access.nav[page]
  }
  const guideUrl = useAiStatus().data?.guide_url
  const navEntries: NavEntry[] = [...NAV, ...(guideUrl
    ? [{ label: 'Yardım', items: [{ to: '/guide', label: 'Kullanım Kılavuzu', href: guideUrl }] }] : [])]
    .map((e) => (isGroup(e) ? { ...e, items: e.items.filter((i) => canSee(i.to)) } : e))
    .filter((e) => (isGroup(e) ? e.items.length > 0 : canSee(e.to)))

  // Sol menü içeriği: masaüstünde kalıcı kenar çubuğu, mobilde (xs) açılır çekmece olarak kullanılır.
  // `compact` = daraltılmış masaüstü görünümü (yalnız simgeler; ad tooltip'te).
  const navItem = (item: NavLink, compact: boolean, nested = false) => {
    const Icon = NAV_ICONS[item.to]
    const badge = badgeFor(item.to)
    // Dış bağlantı (kurum wiki'si) yeni sekmede açılır; Jumbo içi rotalar router ile.
    const target = item.href
      ? { component: 'a' as const, href: item.href, target: '_blank', rel: 'noreferrer' }
      : { component: Link, to: item.to }
    const button = (
      <ListItemButton key={item.to} {...target} selected={isActive(item.to)}
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
            {item.href && <OpenInNewIcon sx={{ fontSize: 15, opacity: 0.7 }} />}
          </>
        )}
      </ListItemButton>
    )
    return compact ? <Tooltip key={item.to} title={item.label} placement="right">{button}</Tooltip> : button
  }

  const navContent = (compact: boolean) => (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', color: '#fff',
               background: BRAND_GRADIENT }}>
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
        {navEntries.map((entry) => {
          if (!isGroup(entry)) return navItem(entry, compact)
          // Daraltılmış menüde başlık yok: simgeler hep görünür
          if (compact) return (
            <Fragment key={entry.label}>
              <Divider sx={{ my: 1, mx: 1.5, borderColor: 'rgba(255,255,255,0.15)' }} />
              {entry.items.map((item) => navItem(item, compact, true))}
            </Fragment>
          )
          const open = !closedGroups.includes(entry.label)
          // Kapalı başlıkta içerideki uyarı sayıları başlığın yanında toplanır
          const hidden = open ? 0 : entry.items.reduce((n, i) => n + badgeFor(i.to), 0)
          return (
            <Fragment key={entry.label}>
              <ListSubheader component="div" disableGutters sx={{ bgcolor: 'transparent', mt: 1, px: 1.25, lineHeight: 'normal', position: 'static' }}>
                <ButtonBase onClick={() => toggleGroup(entry.label)} aria-expanded={open}
                            aria-label={`${entry.label} menüsünü ${open ? 'kapat' : 'aç'}`}
                            sx={{ width: '100%', justifyContent: 'flex-start', gap: 0.75, pl: 1.5, pr: 1, height: 30,
                                  borderRadius: '8px', color: 'rgba(255,255,255,0.5)', fontSize: 11, fontWeight: 600,
                                  letterSpacing: '.08em', textTransform: 'uppercase',
                                  '&:hover': { color: 'rgba(255,255,255,0.85)', bgcolor: 'rgba(255,255,255,0.06)' } }}>
                  <Box component="span" sx={{ flexGrow: 1, textAlign: 'left' }}>{entry.label}</Box>
                  {hidden > 0 && <Chip size="small" color="warning" label={hidden} sx={{ height: 18, fontSize: 11 }} />}
                  <ExpandMoreIcon sx={{ fontSize: 18, transition: 'transform 150ms',
                                        transform: open ? 'rotate(0deg)' : 'rotate(-90deg)' }} />
                </ButtonBase>
              </ListSubheader>
              <Collapse in={open} timeout={150} unmountOnExit>
                {entry.items.map((item) => navItem(item, compact, true))}
              </Collapse>
            </Fragment>
          )
        })}
      </List>
      <Divider sx={{ borderColor: 'rgba(255,255,255,0.10)' }} />
      {/* Kullanıcı: dikey menünün altında (tıklayınca tema / ayarlar / çıkış menüsü yukarı açılır) */}
      <Tooltip title={compact ? `${fullName || username} · ${subLabel}` : ''} placement="right">
        <ButtonBase onClick={(e) => setAnchor(e.currentTarget)} aria-label="Kullanıcı menüsü"
                    sx={{ mx: 1.25, my: 1, px: compact ? 0.5 : 1, py: 0.75, borderRadius: '10px', gap: 1.25,
                          justifyContent: compact ? 'center' : 'flex-start', textAlign: 'left',
                          color: '#fff', transition: 'background-color 150ms',
                          '&:hover': { bgcolor: 'rgba(255,255,255,0.08)' } }}>
          <Avatar src={photo} sx={{ width: 34, height: 34, bgcolor: 'rgba(255,255,255,0.16)', color: '#fff', fontSize: 15, fontWeight: 700 }}>
            {initial}
          </Avatar>
          {!compact && (
            <>
              {/* Uzun LDAP Ad Soyad'ı menüyü bozmasın: tek satır + kısaltma (…) */}
              <Box sx={{ minWidth: 0, flexGrow: 1 }}>
                <Typography variant="body2" noWrap title={fullName || username || undefined}
                            sx={{ fontWeight: 700, lineHeight: 1.3 }}>{fullName || username}</Typography>
                <Typography variant="caption" noWrap component="div"
                            title={subLabel} sx={{ color: 'rgba(255,255,255,0.65)', lineHeight: 1.3 }}>{subLabel}</Typography>
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

      <Box sx={{ flexGrow: 1, minWidth: 0, mr: `${aiDock}px`, transition: 'margin-right 180ms ease' }}>
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
          <Avatar src={photo} sx={{ bgcolor: 'primary.main' }}>{initial}</Avatar>
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
      <AiAssistant navWidth={collapsed ? NAV_W_COMPACT : NAV_W} onDock={setAiDock} />
    </Box>
  )
}
