import AccountTreeIcon from '@mui/icons-material/AccountTree'
import ApartmentIcon from '@mui/icons-material/Apartment'
import BadgeIcon from '@mui/icons-material/Badge'
import BusinessIcon from '@mui/icons-material/Business'
import CalendarMonthIcon from '@mui/icons-material/CalendarMonth'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import EmailIcon from '@mui/icons-material/Email'
import GroupsIcon from '@mui/icons-material/Groups'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import LocationOnIcon from '@mui/icons-material/LocationOn'
import NotesIcon from '@mui/icons-material/Notes'
import PersonIcon from '@mui/icons-material/Person'
import PhoneIcon from '@mui/icons-material/Phone'
import RefreshIcon from '@mui/icons-material/Refresh'
import SearchIcon from '@mui/icons-material/Search'
import WorkIcon from '@mui/icons-material/Work'
import {
  Alert, Avatar, Box, Button, Chip, IconButton, InputAdornment, Skeleton, Stack, TextField, Tooltip, Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useState, type ReactNode } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { AppUser, DirectoryPerson, DirectoryProfile } from '../api/types'
import { CARD_SX, IconBadge, InfoCard, Section, StatusPill, type Tone } from '../components/DetailCards'
import PageHeader from '../components/PageHeader'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { MONO_FONT } from '../theme'
import { formatAuditTime, relativeTime } from '../utils/auditFormat'
import { initials, ROLE_CHIP } from '../utils/peopleLabels'
import { includesFolded } from '../utils/textMatch'

const ISO_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/
const fmtValue = (v: string) => (ISO_RE.test(v) ? formatAuditTime(v) : v)

const SUMMARY_ICONS: Record<string, ReactNode> = {
  full_name: <PersonIcon />, title: <WorkIcon />, department: <ApartmentIcon />, division: <AccountTreeIcon />,
  company: <BusinessIcon />, office: <LocationOnIcon />, location: <LocationOnIcon />, employee_id: <BadgeIcon />,
  employee_type: <BadgeIcon />, mail: <EmailIcon />, upn: <EmailIcon />, account: <PersonIcon />,
  phone: <PhoneIcon />, mobile: <PhoneIcon />, description: <NotesIcon />, created: <CalendarMonthIcon />,
  last_logon: <CalendarMonthIcon />, pwd_last_set: <CalendarMonthIcon />, account_expires: <CalendarMonthIcon />,
}
// Özet kutularının grupları (anahtarlar backend ldap_auth._SUMMARY_FIELDS ile aynı)
const SUMMARY_GROUPS: { title: string; keys: string[] }[] = [
  { title: 'Organizasyon', keys: ['title', 'department', 'division', 'company', 'office', 'location', 'employee_id', 'employee_type'] },
  { title: 'İletişim ve Hesap', keys: ['mail', 'upn', 'account', 'phone', 'mobile', 'description'] },
  { title: 'Hesap Tarihleri (AD)', keys: ['created', 'last_logon', 'pwd_last_set', 'account_expires'] },
]
const flagTone = (f: string): Tone => (f === 'Etkin' ? 'success' : f === 'Şifre süresi dolmaz' ? 'info' : 'error')

function useCopy() {
  const { enqueueSnackbar } = useSnackbar()
  return (value: string) => {
    void navigator.clipboard?.writeText(value)
    enqueueSnackbar('Kopyalandı', { variant: 'success' })
  }
}

/** Profilim (/profile) ve yönetici için başka kullanıcının profili (/profile/:userId). */
export default function Profile() {
  const { userId } = useParams()
  const other = userId !== undefined
  useDocumentTitle(other ? 'Kullanıcı Profili' : 'Profilim')

  const me = useQuery<AppUser>({
    queryKey: ['auth-me'],
    queryFn: async () => (await api.get('/auth/me')).data,
    enabled: !other,
  })
  const users = useQuery<AppUser[]>({
    queryKey: ['users'],
    queryFn: async () => (await api.get('/users')).data,
    enabled: other,
  })
  const dir = useQuery<DirectoryProfile>({
    queryKey: ['directory', userId ?? 'me'],
    queryFn: async () => (await api.get(other ? `/users/${userId}/directory` : '/auth/me/directory')).data,
    staleTime: 5 * 60_000,
  })
  const account = other ? users.data?.find((u) => String(u.id) === userId) : me.data
  const d = dir.data

  return (
    <Box>
      <PageHeader title={other ? 'Kullanıcı Profili' : 'Profilim'}
                  subtitle="Jumbo hesabı ve LDAP / Active Directory'deki bilgiler"
                  actions={d?.status !== 'local' &&
                    <Button variant="outlined" startIcon={<RefreshIcon />} disabled={dir.isFetching}
                            onClick={() => dir.refetch()}>
                      LDAP'tan yeniden oku
                    </Button>
                  } />
      {dir.isLoading ? (
        <Stack spacing={2}><Skeleton variant="rounded" height={140} /><Skeleton variant="rounded" height={320} /></Stack>
      ) : (
        <Stack spacing={3}>
          <Hero account={account} d={d} />
          {d && d.status !== 'ok' && (
            <Alert severity={d.status === 'local' ? 'info' : 'warning'}>{d.message}</Alert>
          )}
          {dir.isError && <Alert severity="error">LDAP bilgileri alınamadı.</Alert>}
          <Box sx={{ display: 'grid', gap: 3, gridTemplateColumns: { xs: '1fr', lg: d?.status === 'ok' ? 'minmax(0, 2fr) minmax(0, 1fr)' : 'minmax(0, 560px)' },
                     alignItems: 'start' }}>
            {d?.status === 'ok' && (
              <Stack spacing={3} sx={{ minWidth: 0 }}>
                <SummaryGroups d={d} />
                <OrgChain d={d} self={d.summary?.find((s) => s.key === 'full_name')?.value || d.username} />
              </Stack>
            )}
            <Stack spacing={3} sx={{ minWidth: 0 }}>
              <JumboAccount account={account} />
              {d?.status === 'ok' && <Groups d={d} />}
              {!!d?.direct_reports?.length && <Reports names={d.direct_reports} />}
            </Stack>
          </Box>
          {d?.status === 'ok' && <AllAttributes d={d} />}
        </Stack>
      )}
    </Box>
  )
}

function Hero({ account, d }: { account?: AppUser; d?: DirectoryProfile }) {
  const field = (k: string) => d?.summary?.find((s) => s.key === k)?.value ?? ''
  const name = field('full_name') || account?.full_name || account?.username || d?.username || ''
  const sub = [field('title'), field('department')].filter(Boolean).join(' · ')
  const mail = field('mail') || account?.email || ''
  const role = ROLE_CHIP[account?.role ?? '']
  return (
    <Box sx={(t) => ({ ...CARD_SX, p: { xs: 2, md: 3 }, display: 'flex', gap: 2.5, alignItems: 'center', flexWrap: 'wrap',
                       background: `linear-gradient(120deg, ${t.palette.primary.main}1f 0%, transparent 60%)` })}>
      <Avatar src={d?.photo ?? undefined}
              sx={{ width: 84, height: 84, fontSize: 30, fontWeight: 700, bgcolor: 'primary.main', color: 'primary.contrastText' }}>
        {initials(name, d?.username ?? account?.username ?? '?')}
      </Avatar>
      <Box sx={{ minWidth: 0, flexGrow: 1 }}>
        <Typography variant="h5" sx={{ fontWeight: 700, wordBreak: 'break-word' }}>{name}</Typography>
        {sub && <Typography variant="body1" color="text.secondary" sx={{ mt: 0.25 }}>{sub}</Typography>}
        {mail && <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>{mail}</Typography>}
        <Stack direction="row" spacing={1} useFlexGap sx={{ mt: 1.25, flexWrap: 'wrap' }}>
          {role && <StatusPill tone={role.color === 'primary' ? 'info' : role.color} label={`Jumbo rolü: ${role.label}`} />}
          {d?.status === 'ok' && <StatusPill tone="info" label="LDAP hesabı" />}
          {d?.status === 'local' && <StatusPill tone="default" label="Yerel hesap" />}
          {(d?.account_flags ?? []).map((f) => <StatusPill key={f} tone={flagTone(f)} label={`AD: ${f}`} />)}
        </Stack>
      </Box>
    </Box>
  )
}

function SummaryGroups({ d }: { d: DirectoryProfile }) {
  const byKey = new Map((d.summary ?? []).map((s) => [s.key, s]))
  return (
    <>
      {SUMMARY_GROUPS.map((g) => {
        const items = g.keys.map((k) => byKey.get(k)).filter((s): s is NonNullable<typeof s> => !!s)
        if (!items.length) return null
        return (
          <Section key={g.title} title={g.title}>
            <Box sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', xl: 'repeat(3, 1fr)' } }}>
              {items.map((s) => (
                <InfoCard key={s.key} title={s.label} value={fmtValue(s.value)} icon={SUMMARY_ICONS[s.key]}
                          sub={ISO_RE.test(s.value) ? relativeTime(s.value) : undefined} />
              ))}
            </Box>
          </Section>
        )
      })}
    </>
  )
}

function PersonRow({ p, label, highlight }: { p: Pick<DirectoryPerson, 'name' | 'title' | 'department' | 'mail'>; label: string; highlight?: boolean }) {
  return (
    <Box sx={(t) => ({ display: 'flex', gap: 1.5, alignItems: 'center', p: 1.25, borderRadius: '10px',
                       border: 1, borderColor: highlight ? t.palette.primary.main : t.palette.divider,
                       bgcolor: highlight ? `${t.palette.primary.main}14` : 'transparent' })}>
      <Avatar sx={{ width: 36, height: 36, fontSize: 14, fontWeight: 600, bgcolor: highlight ? 'primary.main' : 'action.selected',
                    color: highlight ? 'primary.contrastText' : 'text.primary' }}>
        {initials(p.name, p.name || '?')}
      </Avatar>
      <Box sx={{ minWidth: 0, flexGrow: 1 }}>
        <Typography variant="body2" sx={{ fontWeight: 650 }}>{p.name}</Typography>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
          {[p.title, p.department].filter(Boolean).join(' · ') || '—'}
        </Typography>
        {p.mail && <Typography variant="caption" color="text.secondary">{p.mail}</Typography>}
      </Box>
      <Chip size="small" variant="outlined" label={label} />
    </Box>
  )
}

/** Yönetici zinciri: en üstten kişiye doğru; ayrıca dizindeki yeri (OU yolu). */
function OrgChain({ d, self }: { d: DirectoryProfile; self: string }) {
  const field = (k: string) => d.summary?.find((s) => s.key === k)?.value ?? ''
  const chain = [...(d.managers ?? [])].reverse()
  return (
    <Section title="Bağlı Olduğu Yöneticiler" aside={chain.length ? `${chain.length} kademe` : undefined}>
      <Box sx={{ ...CARD_SX, p: 2 }}>
        {chain.length === 0 && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            LDAP kaydında yönetici (manager) bilgisi yok.
          </Typography>
        )}
        <Stack spacing={0}>
          {chain.map((m, i) => (
            <Box key={m.dn}>
              <PersonRow p={m} label={i === chain.length - 1 ? 'Doğrudan yöneticisi' : `${chain.length - i}. üst yönetici`} />
              <Box sx={{ ml: 3.25, height: 14, borderLeft: 2, borderColor: 'divider' }} />
            </Box>
          ))}
          <PersonRow p={{ name: self, title: field('title'), department: field('department'), mail: '' }} label="Kendisi" highlight />
        </Stack>
        {!!d.ou_path?.length && (
          <Box sx={{ mt: 2 }}>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
              Dizindeki yeri (OU)
            </Typography>
            <Stack direction="row" spacing={0.5} useFlexGap sx={{ flexWrap: 'wrap', alignItems: 'center' }}>
              {d.ou_path.map((ou, i) => (
                <Stack key={i} direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
                  {i > 0 && <Typography color="text.disabled">›</Typography>}
                  <Chip size="small" label={ou} />
                </Stack>
              ))}
            </Stack>
          </Box>
        )}
      </Box>
    </Section>
  )
}

function JumboAccount({ account }: { account?: AppUser }) {
  if (!account) return null
  const role = ROLE_CHIP[account.role]
  const rows: [string, ReactNode][] = [
    ['Kullanıcı adı', <Box key="u" component="span" sx={{ fontFamily: MONO_FONT, fontSize: 13 }}>{account.username}</Box>],
    ['Jumbo rolü', role?.label ?? account.role],
    ['Giriş türü', account.auth_source === 'ldap' ? 'LDAP / Active Directory' : 'Yerel hesap'],
    ['Son giriş', account.last_login ? `${formatAuditTime(account.last_login)} (${relativeTime(account.last_login)})` : '—'],
  ]
  return (
    <Section title="Jumbo Hesabı">
      <Box sx={{ ...CARD_SX, overflow: 'hidden' }}>
        {rows.map(([label, value], i) => (
          <Box key={label} sx={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: 1.5, px: 2, py: 1.1,
                                 borderTop: i ? 1 : 0, borderColor: 'divider' }}>
            <Typography variant="body2" color="text.secondary">{label}</Typography>
            <Typography variant="body2" component="div" sx={{ wordBreak: 'break-word' }}>{value}</Typography>
          </Box>
        ))}
        <Box sx={{ px: 2, py: 1.25, borderTop: 1, borderColor: 'divider' }}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 0.75 }}>Jumbo ekipleri</Typography>
          <Stack direction="row" spacing={0.75} useFlexGap sx={{ flexWrap: 'wrap' }}>
            {(account.team_names ?? []).length
              ? account.team_names!.map((t) => <Chip key={t} size="small" color="primary" variant="outlined" label={t} />)
              : <Typography variant="body2" color="text.secondary">Ekip yok</Typography>}
          </Stack>
        </Box>
      </Box>
    </Section>
  )
}

function Groups({ d }: { d: DirectoryProfile }) {
  const [q, setQ] = useState('')
  const groups = d.groups ?? []
  const shown = groups.filter((g) => includesFolded(g.name, q))
  return (
    <Section title="AD Grupları" aside={`${groups.length} grup`}>
      <Box sx={{ ...CARD_SX, p: 1.5 }}>
        {groups.length > 8 && (
          <TextField size="small" fullWidth placeholder="Grup ara" value={q} onChange={(e) => setQ(e.target.value)} sx={{ mb: 1 }}
                     slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }} />
        )}
        {!groups.length && <Typography variant="body2" color="text.secondary">Grup üyeliği yok.</Typography>}
        <Stack spacing={0.5} sx={{ maxHeight: 360, overflowY: 'auto' }}>
          {shown.map((g) => (
            <Tooltip key={g.dn} title={g.dn} placement="left">
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1, py: 0.75, borderRadius: '8px',
                         '&:hover': { bgcolor: 'action.hover' } }}>
                <GroupsIcon fontSize="small" sx={{ color: 'text.secondary' }} />
                <Typography variant="body2" sx={{ flexGrow: 1, minWidth: 0, wordBreak: 'break-word' }}>{g.name}</Typography>
                {g.mapped_role && (
                  <StatusPill size="small" tone="info" label={`Rol eşlemesi: ${ROLE_CHIP[g.mapped_role]?.label ?? g.mapped_role}`} />
                )}
              </Box>
            </Tooltip>
          ))}
        </Stack>
        {d.group_source === 'group_search' && (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
            Gruplar Ayarlar &gt; LDAP'taki grup aramasıyla bulundu (kayıtta memberOf yok).
          </Typography>
        )}
      </Box>
    </Section>
  )
}

function Reports({ names }: { names: string[] }) {
  return (
    <Section title="Doğrudan Bağlı Çalışanlar" aside={`${names.length} kişi`}>
      <Box sx={{ ...CARD_SX, p: 1.5 }}>
        <Stack direction="row" spacing={0.75} useFlexGap sx={{ flexWrap: 'wrap' }}>
          {names.map((n) => <Chip key={n} size="small" avatar={<Avatar>{initials(n, n)}</Avatar>} label={n} />)}
        </Stack>
      </Box>
    </Section>
  )
}

/** LDAP'ın döndürdüğü TÜM nitelikler (şifre alanları sunucuda çıkarılır). */
function AllAttributes({ d }: { d: DirectoryProfile }) {
  const [q, setQ] = useState('')
  const copy = useCopy()
  const attrs = d.attributes ?? []
  const shown = attrs.filter((a) => includesFolded(a.name, q) || a.values.some((v) => includesFolded(v, q)))
  return (
    <Section title={`Tüm LDAP Bilgileri (${attrs.length} alan)`}
             aside="LDAP'ın bu kişi için döndürdüğü her alan; şifre alanları gösterilmez">
      <Box sx={{ ...CARD_SX, overflow: 'hidden' }}>
        <Box sx={{ p: 1.5, borderBottom: 1, borderColor: 'divider', display: 'flex', gap: 1.5, alignItems: 'center', flexWrap: 'wrap' }}>
          <TextField size="small" placeholder="Alan adı veya değer ara" value={q} onChange={(e) => setQ(e.target.value)}
                     sx={{ minWidth: 280, flexGrow: 1, maxWidth: 420 }}
                     slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }} />
          {d.dn && (
            <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center', minWidth: 0 }}>
              <IconBadge size={26}><InfoOutlinedIcon /></IconBadge>
              <Typography variant="caption" color="text.secondary" sx={{ fontFamily: MONO_FONT, wordBreak: 'break-all' }}>{d.dn}</Typography>
              <IconButton size="small" aria-label="DN kopyala" onClick={() => copy(d.dn!)}><ContentCopyIcon sx={{ fontSize: 16 }} /></IconButton>
            </Stack>
          )}
        </Box>
        {shown.map((a, i) => (
          <Box key={a.name} sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr auto', md: '240px 1fr auto' }, columnGap: 2,
                                  px: 2, py: 1, borderTop: i ? 1 : 0, borderColor: 'divider', alignItems: 'start',
                                  '&:hover': { bgcolor: 'action.hover' } }}>
            <Typography variant="body2" sx={{ fontFamily: MONO_FONT, fontSize: 12.5, fontWeight: 600, pt: 0.25,
                                              gridColumn: { xs: '1 / -1', md: 'auto' } }}>
              {a.name}
            </Typography>
            <Box sx={{ minWidth: 0 }}>
              {a.values.map((v, j) => (
                <Typography key={j} variant="body2" sx={{ wordBreak: 'break-word', py: 0.125 }}>{fmtValue(v)}</Typography>
              ))}
            </Box>
            <Tooltip title="Kopyala">
              <IconButton size="small" aria-label={`${a.name} kopyala`} onClick={() => copy(a.values.join('\n'))}>
                <ContentCopyIcon sx={{ fontSize: 16 }} />
              </IconButton>
            </Tooltip>
          </Box>
        ))}
        {!shown.length && <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>Eşleşen alan yok.</Typography>}
      </Box>
    </Section>
  )
}
