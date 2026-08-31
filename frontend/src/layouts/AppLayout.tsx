import ArrowDropDownIcon from '@mui/icons-material/ArrowDropDown'
import DarkModeIcon from '@mui/icons-material/DarkMode'
import LightModeIcon from '@mui/icons-material/LightMode'
import LogoutIcon from '@mui/icons-material/Logout'
import MenuIcon from '@mui/icons-material/Menu'
import SettingsIcon from '@mui/icons-material/Settings'
import {
  AppBar, Avatar, Badge, Box, Button, Chip, Container, Divider, Drawer, IconButton, List,
  ListItemButton, ListItemIcon, ListItemText, ListSubheader, Menu, MenuItem, Switch, Toolbar,
  Typography,
} from '@mui/material'
import { Fragment, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useThemeMode } from '../App'
import { useAuth } from '../auth/AuthContext'
import { usePageAccess } from '../hooks/usePageAccess'
import { useDiscoveredCount } from '../pages/Discovery'
import { usePolicyViolationCount } from '../pages/Policy'
import { usePendingProposalCount } from '../pages/Proposals'

// Navbar: sık kullanılanlar tekil; kalanı 'Analiz' ve 'İşlemler' açılır menülerinde gruplanır.
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
    { to: '/proposals', label: 'Devir Önerileri' },
    { to: '/deployments', label: 'Dağıtım' },
    { to: '/deployments/runs', label: 'Tüm Çalıştırmalar' },
  ] },
]

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
  const [navMenu, setNavMenu] = useState<{ label: string; el: HTMLElement } | null>(null)  // masaüstü grup dropdown'u
  const access = usePageAccess()
  const pendingCount = usePendingProposalCount()
  const shadowCount = useDiscoveredCount()
  const violationCount = usePolicyViolationCount()

  const isActive = (to: string) => location.pathname === to
  const badgeFor = (to: string) =>
    to === '/proposals' ? pendingCount
      : to === '/discovery' ? shadowCount
        : to === '/policy' ? violationCount : 0
  const groupBadge = (g: NavGroup) => g.items.reduce((n, i) => n + badgeFor(i.to), 0)
  const groupActive = (g: NavGroup) => g.items.some((i) => isActive(i.to))
  // Erişimi olmayan rotaları gizle (bkz. usePageAccess); boşalan grupları düş
  const canSee = (to: string) => { const page = PAGE_FOR_PATH[to]; return !page || access[page] }
  const navEntries: NavEntry[] = NAV
    .map((e) => (isGroup(e) ? { ...e, items: e.items.filter((i) => canSee(i.to)) } : e))
    .filter((e) => (isGroup(e) ? e.items.length > 0 : canSee(e.to)))

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <AppBar position="sticky" sx={{ bgcolor: '#8f1d22', backgroundImage: 'none' }}>
        <Toolbar sx={{ gap: 1 }}>
          {/* Mobilde (xs) menü hamburger'ı; md+ gizli (butonlar satırda görünür). */}
          <IconButton color="inherit" edge="start" aria-label="Menüyü aç"
                      onClick={() => setDrawerOpen(true)}
                      sx={{ display: { xs: 'inline-flex', md: 'none' } }}>
            <MenuIcon />
          </IconButton>
          <Box component={Link} to="/"
               sx={{ display: 'flex', alignItems: 'center', gap: 1, mr: { xs: 0.5, md: 3 },
                     textDecoration: 'none', color: 'inherit', '&:hover': { opacity: 0.9 } }}>
            <Box component="img" src="/favicon.svg" alt="JUMBO"
                 sx={{ width: 38, height: 38, display: 'block' }} />
            <Box sx={{ display: { xs: 'none', sm: 'block' } }}>
              <Typography variant="h6" sx={{ lineHeight: 1.1 }}>JUMBO</Typography>
              <Typography variant="caption" sx={{ opacity: 0.8 }}>Sertifika Yönetimi</Typography>
            </Box>
          </Box>
          {/* Yatay nav yalnız md+; xs'te Drawer'a taşındı. Gruplar açılır menüdür. */}
          <Box sx={{ display: { xs: 'none', md: 'flex' }, alignItems: 'center', gap: 1 }}>
            {navEntries.map((entry) => (isGroup(entry) ? (
              <Button
                key={entry.label}
                color="inherit"
                onClick={(e) => setNavMenu({ label: entry.label, el: e.currentTarget })}
                endIcon={<ArrowDropDownIcon sx={{ ml: -0.75 }} />}
                sx={{
                  fontWeight: 600,
                  borderBottom: groupActive(entry) ? '3px solid #fff' : '3px solid transparent',
                  borderRadius: 0,
                }}
              >
                {groupBadge(entry) > 0 ? (
                  <Badge color="warning" badgeContent={groupBadge(entry)} sx={{ '& .MuiBadge-badge': { right: -6, top: 2 } }}>
                    {entry.label}
                  </Badge>
                ) : entry.label}
              </Button>
            ) : (
              <Button
                key={entry.to}
                component={Link}
                to={entry.to}
                color="inherit"
                sx={{
                  fontWeight: 600,
                  borderBottom: isActive(entry.to) ? '3px solid #fff' : '3px solid transparent',
                  borderRadius: 0,
                }}
              >
                {badgeFor(entry.to) > 0 ? (
                  <Badge color="warning" badgeContent={badgeFor(entry.to)} sx={{ '& .MuiBadge-badge': { right: -6, top: 2 } }}>
                    {entry.label}
                  </Badge>
                ) : entry.label}
              </Button>
            )))}
          </Box>
          {/* Grup dropdown menüsü (tek Menu; açık grup navMenu.label ile belirlenir). */}
          <Menu anchorEl={navMenu?.el} open={!!navMenu} onClose={() => setNavMenu(null)}
                slotProps={{ paper: { sx: { mt: 0.5, minWidth: 210 } } }}>
            {navEntries.filter(isGroup).find((g) => g.label === navMenu?.label)?.items.map((item) => (
              <MenuItem key={item.to} component={Link} to={item.to} selected={isActive(item.to)}
                        onClick={() => setNavMenu(null)}>
                <ListItemText slotProps={{ primary: { sx: { fontWeight: isActive(item.to) ? 700 : 500 } } }}>
                  {item.label}
                </ListItemText>
                {badgeFor(item.to) > 0 && (
                  <Chip size="small" color="warning" label={badgeFor(item.to)} sx={{ ml: 1.5 }} />
                )}
              </MenuItem>
            ))}
          </Menu>
          <Box sx={{ flexGrow: 1 }} />
          <Button color="inherit" onClick={(e) => setAnchor(e.currentTarget)} sx={{ textTransform: 'none', minWidth: 0 }}>
            <Avatar sx={{ width: 32, height: 32, mr: { xs: 0, sm: 1 }, bgcolor: 'rgba(255,255,255,0.25)' }}>
              {(fullName || username || '?')[0]?.toUpperCase()}
            </Avatar>
            {/* Uzun LDAP Ad Soyad'ı navbar'ı bozmasın: tek satır + kısaltma (…); xs'te yalnız avatar. */}
            <Box sx={{ textAlign: 'left', minWidth: 0, maxWidth: { xs: 110, sm: 200 }, display: { xs: 'none', sm: 'block' } }}>
              <Typography variant="body2" noWrap title={fullName || username || undefined}
                          sx={{ fontWeight: 700 }}>{fullName || username}</Typography>
              <Typography variant="caption" noWrap
                          sx={{ opacity: 0.8, display: 'block' }}>{ROLE_LABELS[role ?? ''] ?? role}</Typography>
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

      {/* Mobil navigasyon çekmecesi (xs). Masaüstünde açılmaz — hamburger yalnız xs'te görünür. */}
      <Drawer anchor="left" open={drawerOpen} onClose={() => setDrawerOpen(false)}
              ModalProps={{ keepMounted: true }}>
        <Box sx={{ width: 264 }} role="presentation">
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 2, py: 1.75,
                     bgcolor: '#8f1d22', color: '#fff' }}>
            <Box component="img" src="/favicon.svg" alt="JUMBO" sx={{ width: 32, height: 32 }} />
            <Box>
              <Typography variant="h6" sx={{ lineHeight: 1.1 }}>JUMBO</Typography>
              <Typography variant="caption" sx={{ opacity: 0.8 }}>Sertifika Yönetimi</Typography>
            </Box>
          </Box>
          <List sx={{ py: 1 }}>
            {navEntries.map((entry) => (isGroup(entry) ? (
              <Fragment key={entry.label}>
                <ListSubheader sx={{ bgcolor: 'transparent', lineHeight: '30px', mt: 0.5,
                                     fontSize: 11, letterSpacing: '.06em', textTransform: 'uppercase' }}>
                  {entry.label}
                </ListSubheader>
                {entry.items.map((item) => (
                  <ListItemButton key={item.to} component={Link} to={item.to} sx={{ pl: 3,
                                    '&.Mui-selected': { borderLeft: '3px solid', borderColor: 'primary.main' } }}
                                  selected={isActive(item.to)} onClick={() => setDrawerOpen(false)}>
                    <ListItemText primary={item.label}
                                  slotProps={{ primary: { sx: { fontWeight: isActive(item.to) ? 700 : 500 } } }} />
                    {badgeFor(item.to) > 0 && <Chip size="small" color="warning" label={badgeFor(item.to)} />}
                  </ListItemButton>
                ))}
              </Fragment>
            ) : (
              <ListItemButton key={entry.to} component={Link} to={entry.to}
                              selected={isActive(entry.to)} onClick={() => setDrawerOpen(false)}
                              sx={{ '&.Mui-selected': { borderLeft: '3px solid', borderColor: 'primary.main' } }}>
                <ListItemText primary={entry.label}
                              slotProps={{ primary: { sx: { fontWeight: isActive(entry.to) ? 700 : 500 } } }} />
                {badgeFor(entry.to) > 0 && <Chip size="small" color="warning" label={badgeFor(entry.to)} />}
              </ListItemButton>
            )))}
          </List>
        </Box>
      </Drawer>

      <Container maxWidth={false} sx={{ py: 3 }}>
        <Outlet />
      </Container>
    </Box>
  )
}
