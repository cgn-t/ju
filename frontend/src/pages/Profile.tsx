import AccountTreeIcon from '@mui/icons-material/AccountTree'
import ApartmentIcon from '@mui/icons-material/Apartment'
import BadgeIcon from '@mui/icons-material/Badge'
import BusinessIcon from '@mui/icons-material/Business'
import EmailIcon from '@mui/icons-material/Email'
import GroupsIcon from '@mui/icons-material/Groups'
import LocationOnIcon from '@mui/icons-material/LocationOn'
import NotesIcon from '@mui/icons-material/Notes'
import PersonIcon from '@mui/icons-material/Person'
import PhoneIcon from '@mui/icons-material/Phone'
import RefreshIcon from '@mui/icons-material/Refresh'
import WorkIcon from '@mui/icons-material/Work'
import { Alert, Avatar, Box, Button, Chip, Skeleton, Stack, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { AppUser, DirectoryPerson, DirectoryProfile } from '../api/types'
import { CARD_SX, InfoCard, Section, StatusPill, type Tone } from '../components/DetailCards'
import PageHeader from '../components/PageHeader'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { formatAuditTime, relativeTime } from '../utils/auditFormat'
import { initials, ROLE_CHIP } from '../utils/peopleLabels'

const ISO_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/
const fmtValue = (v: string) => (ISO_RE.test(v) ? formatAuditTime(v) : v)

const SUMMARY_ICONS: Record<string, ReactNode> = {
  team: <GroupsIcon />, full_name: <PersonIcon />, title: <WorkIcon />, department: <ApartmentIcon />, division: <AccountTreeIcon />,
  company: <BusinessIcon />, office: <LocationOnIcon />, location: <LocationOnIcon />, employee_id: <BadgeIcon />,
  employee_type: <BadgeIcon />, mail: <EmailIcon />, upn: <EmailIcon />, account: <PersonIcon />,
  phone: <PhoneIcon />, mobile: <PhoneIcon />, description: <NotesIcon />,
}
// Özet kutularının grupları (anahtarlar backend ldap_auth._SUMMARY_FIELDS ile aynı)
const SUMMARY_GROUPS: { title: string; keys: string[] }[] = [
  { title: 'Organizasyon', keys: ['team', 'title', 'department', 'division', 'company', 'office', 'location', 'employee_id', 'employee_type'] },
  { title: 'İletişim ve Hesap', keys: ['mail', 'upn', 'account', 'phone', 'mobile', 'description'] },
]
const flagTone = (f: string): Tone => (f === 'Etkin' ? 'success' : f === 'Şifre süresi dolmaz' ? 'info' : 'error')

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
          {d?.status === 'ok' && (
            <Box sx={{ display: 'grid', gap: 3, gridTemplateColumns: { xs: '1fr', xl: 'minmax(0, 3fr) minmax(0, 2fr)' },
                       alignItems: 'start' }}>
              <Stack spacing={3} sx={{ minWidth: 0 }}><SummaryGroups d={d} /></Stack>
              <OrgChain d={d} self={d.summary?.find((s) => s.key === 'full_name')?.value || d.username} />
            </Box>
          )}
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
