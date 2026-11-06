import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import DnsOutlinedIcon from '@mui/icons-material/DnsOutlined'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import GroupsOutlinedIcon from '@mui/icons-material/GroupsOutlined'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlineOutlined'
import LockOutlinedIcon from '@mui/icons-material/LockOutlined'
import SearchIcon from '@mui/icons-material/Search'
import VerifiedUserOutlinedIcon from '@mui/icons-material/VerifiedUserOutlined'
import {
  Box, ButtonBase, Collapse, FormControlLabel, InputAdornment, Stack, Switch, TextField,
  ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import { alpha, type Theme } from '@mui/material/styles'
import { useMemo, useState } from 'react'
import type { MappedDomain } from '../api/types'
import { CARD_SX, IconBadge, type Tone } from './DetailCards'

/** Canlı doğrulama durumu → nokta rengi + kısa etiket (domain penceresindeki uzun etiketlerin özeti). */
const LIVE: Record<string, { tone: Tone; label: string }> = {
  match: { tone: 'success', label: 'Eşleşiyor' },
  mismatch: { tone: 'error', label: 'EŞLEŞMİYOR' },
  chain_incomplete: { tone: 'warning', label: 'Ara sertifika eksik' },
  unreachable: { tone: 'warning', label: 'Erişilemedi' },
  no_mapping: { tone: 'warning', label: 'Server bağlı değil' },
  not_checkable: { tone: 'default', label: 'Kontrol edilemez' },
}
const live = (d: MappedDomain) => (d.live_check_status ? LIVE[d.live_check_status] : undefined)

const toneColor = (t: Theme, tone: Tone) =>
  tone === 'default' ? t.palette.text.disabled : t.palette[tone].main

function Dot({ d }: { d: MappedDomain }) {
  const l = live(d)
  return (
    <Box component="span" sx={(t) => ({
      width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
      backgroundColor: l ? toneColor(t, l.tone) : 'transparent',
      border: l ? 'none' : `1.5px solid ${t.palette.text.disabled}`,
    })} />
  )
}

function TeamPill({ team }: { team?: string | null }) {
  return (
    <Box component="span" sx={(t) => ({
      px: 1, py: 0.125, borderRadius: 999, fontSize: 11.5, fontWeight: 600, whiteSpace: 'nowrap',
      color: 'text.secondary', backgroundColor: alpha(t.palette.text.primary, 0.06),
    })}>{team ?? 'ekibi yok'}</Box>
  )
}

function SearchBox({ value, onChange, placeholder = 'Domain veya ekip ara' }: {
  value: string; onChange: (v: string) => void; placeholder?: string
}) {
  return (
    <TextField size="small" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
               sx={{ minWidth: { xs: '100%', sm: 240 } }}
               slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }} />
  )
}

const matches = (d: MappedDomain, q: string) => {
  const s = q.trim().toLocaleLowerCase('tr')
  return !s || d.domain.toLocaleLowerCase('tr').includes(s) || (d.team ?? '').toLocaleLowerCase('tr').includes(s)
}
const byName = (a: MappedDomain, b: MappedDomain) => a.domain.localeCompare(b.domain)
// Kendi ekibimin (açabildiğim) domainleri önce, sonra alfabetik
const mineFirst = (a: MappedDomain, b: MappedDomain) =>
  Number(a.can_view === false) - Number(b.can_view === false) || byName(a, b)

export type LinksVariant = 'a' | 'b' | 'c'

/**
 * Sertifika → Bağlantılar sekmesi: bağlı domainler (Server / Trusted).
 * Çok domainde kalabalık olmasın diye: arama, Server/Trusted ayrımı, kendi ekibim filtresi;
 * başka SY ekibinin domaini kilit simgesiyle gösterilir ve tıklanınca uyarı açılır (onOpen).
 */
export default function CertificateLinksTab({ domains, onOpen, variant = 'a' }: {
  domains: MappedDomain[]; onOpen: (d: MappedDomain) => void; variant?: LinksVariant
}) {
  if (domains.length === 0) {
    return (
      <Box sx={{ ...CARD_SX, p: 3, textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">Bu sertifika hiçbir domain'e bağlı değil</Typography>
      </Box>
    )
  }
  if (variant === 'b') return <GroupedByTeam domains={domains} onOpen={onOpen} />
  if (variant === 'c') return <TwoColumnChips domains={domains} onOpen={onOpen} />
  return <SegmentedList domains={domains} onOpen={onOpen} />
}

/* ---------------- A: Server/Trusted düğmesi + sade liste ---------------- */
function SegmentedList({ domains, onOpen }: { domains: MappedDomain[]; onOpen: (d: MappedDomain) => void }) {
  const server = domains.filter((d) => d.mapping_type === 'server')
  const trusted = domains.filter((d) => d.mapping_type !== 'server')
  const [kind, setKind] = useState<'server' | 'client'>(server.length ? 'server' : 'client')
  const [q, setQ] = useState('')
  const [mine, setMine] = useState(false)
  const rows = (kind === 'server' ? server : trusted)
    .filter((d) => matches(d, q) && (!mine || d.can_view !== false)).sort(mineFirst)
  return (
    <Box sx={{ ...CARD_SX, p: 0, overflow: 'hidden' }}>
      <Stack direction={{ xs: 'column', sm: 'row' }} useFlexGap
             sx={{ gap: 1.5, p: { xs: 2, md: 2.5 }, alignItems: { sm: 'center' }, borderBottom: 1, borderColor: 'divider' }}>
        <ToggleButtonGroup exclusive size="small" value={kind} onChange={(_, v) => v && setKind(v)}>
          <ToggleButton value="server" sx={{ px: 2, gap: 1, textTransform: 'none', fontWeight: 600 }}>
            <DnsOutlinedIcon fontSize="small" /> Server <CountBadge n={server.length} />
          </ToggleButton>
          <ToggleButton value="client" sx={{ px: 2, gap: 1, textTransform: 'none', fontWeight: 600 }}>
            <VerifiedUserOutlinedIcon fontSize="small" /> Trusted <CountBadge n={trusted.length} />
          </ToggleButton>
        </ToggleButtonGroup>
        <Box sx={{ flexGrow: 1 }} />
        <FormControlLabel control={<Switch size="small" checked={mine} onChange={(e) => setMine(e.target.checked)} />}
                          label={<Typography variant="body2">Yalnız ekibim</Typography>} />
        <SearchBox value={q} onChange={setQ} />
      </Stack>
      <Box sx={{ maxHeight: 460, overflowY: 'auto' }}>
        {rows.length === 0 && (
          <Typography variant="body2" color="text.secondary" sx={{ p: 3, textAlign: 'center' }}>Eşleşen domain yok</Typography>
        )}
        {rows.map((d, i) => <ListRow key={`${d.domain_id}-${d.mapping_type}`} d={d} first={i === 0} onOpen={onOpen} />)}
      </Box>
    </Box>
  )
}

function CountBadge({ n }: { n: number }) {
  return (
    <Box component="span" sx={(t) => ({
      minWidth: 22, px: 0.75, borderRadius: 999, fontSize: 12, fontWeight: 700, lineHeight: '20px', textAlign: 'center',
      backgroundColor: alpha(t.palette.text.primary, 0.08),
    })}>{n}</Box>
  )
}

function ListRow({ d, first, onOpen, showKind }: {
  d: MappedDomain; first: boolean; onOpen: (d: MappedDomain) => void; showKind?: boolean
}) {
  const locked = d.can_view === false
  const l = live(d)
  return (
    <ButtonBase onClick={() => onOpen(d)} sx={(t) => ({
      width: '100%', display: 'flex', alignItems: 'center', gap: 1.5, px: { xs: 2, md: 2.5 }, py: 1.25,
      textAlign: 'left', borderTop: first ? 0 : 1, borderColor: 'divider',
      '&:hover': { backgroundColor: alpha(t.palette.primary.main, 0.04) },
    })}>
      <Dot d={d} />
      <Box sx={{ minWidth: 0, flexGrow: 1 }}>
        <Typography variant="body2" noWrap sx={{ fontWeight: 600, color: locked ? 'text.secondary' : 'text.primary' }}>
          {d.domain}
        </Typography>
        <Typography variant="caption" color="text.secondary" noWrap component="div">
          {showKind && `${d.mapping_type === 'server' ? 'Server' : 'Trusted'} · `}
          {locked ? 'Başka ekibin domaini — detayı görüntüleyemezsiniz' : l ? l.label : 'Canlı doğrulama yok'}
        </Typography>
      </Box>
      <TeamPill team={d.team} />
      {locked
        ? <Tooltip title="Görüntüleme yetkiniz yok"><LockOutlinedIcon fontSize="small" sx={{ color: 'text.disabled' }} /></Tooltip>
        : <ChevronRightIcon fontSize="small" sx={{ color: 'text.disabled' }} />}
    </ButtonBase>
  )
}

/* ---------------- B: özet şeridi + ekiplere göre gruplar ---------------- */
function GroupedByTeam({ domains, onOpen }: { domains: MappedDomain[]; onOpen: (d: MappedDomain) => void }) {
  const [q, setQ] = useState('')
  const groups = useMemo(() => {
    const m = new Map<string, MappedDomain[]>()
    for (const d of domains.filter((x) => matches(x, q))) {
      const k = d.team ?? 'Ekibi yok'
      m.set(k, [...(m.get(k) ?? []), d])
    }
    // Erişebildiğim ekipler önce, sonra alfabetik
    return [...m.entries()].map(([team, list]) => ({ team, list: list.sort(byName), mine: list.some((d) => d.can_view !== false) }))
      .sort((a, b) => Number(b.mine) - Number(a.mine) || a.team.localeCompare(b.team))
  }, [domains, q])
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const server = domains.filter((d) => d.mapping_type === 'server').length
  const teams = new Set(domains.map((d) => d.team ?? '')).size
  const viewable = domains.filter((d) => d.can_view !== false).length
  const problems = domains.filter((d) => ['mismatch', 'unreachable', 'chain_incomplete'].includes(d.live_check_status ?? '')).length
  return (
    <Stack spacing={2}>
      <Box sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: { xs: '1fr 1fr', md: 'repeat(4, 1fr)' } }}>
        <Stat icon={<DnsOutlinedIcon />} label="Server" value={server} />
        <Stat icon={<VerifiedUserOutlinedIcon />} label="Trusted" value={domains.length - server} tone="info" />
        <Stat icon={<GroupsOutlinedIcon />} label="SY ekibi" value={teams} sub={`${viewable} domain sizin ekibinizde`} />
        <Stat icon={<ErrorOutlineIcon />} label="Canlıda sorun" value={problems} tone={problems ? 'error' : 'success'}
              sub="Ekibinizin domainlerinde" />
      </Box>
      <Box sx={{ ...CARD_SX, p: 0, overflow: 'hidden' }}>
        <Stack direction="row" sx={{ p: { xs: 2, md: 2.5 }, alignItems: 'center', borderBottom: 1, borderColor: 'divider', gap: 1.5, flexWrap: 'wrap' }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, flexGrow: 1 }}>Ekiplere göre bağlı domainler</Typography>
          <SearchBox value={q} onChange={setQ} />
        </Stack>
        {groups.map(({ team, list, mine }, gi) => {
          const isOpen = open[team] ?? mine
          return (
            <Box key={team} sx={{ borderTop: gi ? 1 : 0, borderColor: 'divider' }}>
              <ButtonBase onClick={() => setOpen({ ...open, [team]: !isOpen })}
                          sx={{ width: '100%', justifyContent: 'flex-start', gap: 1.5, px: { xs: 2, md: 2.5 }, py: 1.5 }}>
                <ExpandMoreIcon fontSize="small" sx={{ transform: isOpen ? 'none' : 'rotate(-90deg)', transition: 'transform .15s', color: 'text.secondary' }} />
                <Typography variant="body2" sx={{ fontWeight: 700 }}>{team}</Typography>
                {mine
                  ? <Box component="span" sx={(t) => ({ fontSize: 11.5, fontWeight: 700, px: 1, borderRadius: 999, color: t.palette.success.main, backgroundColor: alpha(t.palette.success.main, 0.12) })}>Sizin ekibiniz</Box>
                  : <LockOutlinedIcon sx={{ fontSize: 16, color: 'text.disabled' }} />}
                <Box sx={{ flexGrow: 1 }} />
                <Typography variant="caption" color="text.secondary">
                  {list.filter((d) => d.mapping_type === 'server').length} Server · {list.filter((d) => d.mapping_type !== 'server').length} Trusted
                </Typography>
              </ButtonBase>
              <Collapse in={isOpen} unmountOnExit>
                <Box sx={{ px: { xs: 2, md: 2.5 }, pb: 2, display: 'grid', gap: 1, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' } }}>
                  {list.map((d) => <MiniCard key={`${d.domain_id}-${d.mapping_type}`} d={d} onOpen={onOpen} />)}
                </Box>
              </Collapse>
            </Box>
          )
        })}
        {groups.length === 0 && (
          <Typography variant="body2" color="text.secondary" sx={{ p: 3, textAlign: 'center' }}>Eşleşen domain yok</Typography>
        )}
      </Box>
    </Stack>
  )
}

function Stat({ icon, label, value, sub, tone = 'default' }: { icon: React.ReactNode; label: string; value: number; sub?: string; tone?: Tone }) {
  return (
    <Box sx={{ ...CARD_SX, p: 1.75, display: 'flex', alignItems: 'center', gap: 1.5 }}>
      <IconBadge size={36} tone={tone}>{icon}</IconBadge>
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="caption" color="text.secondary">{label}</Typography>
        <Typography variant="h6" sx={{ fontWeight: 700, lineHeight: 1.1 }}>{value}</Typography>
        {sub && <Typography variant="caption" color="text.secondary" noWrap component="div">{sub}</Typography>}
      </Box>
    </Box>
  )
}

function MiniCard({ d, onOpen }: { d: MappedDomain; onOpen: (d: MappedDomain) => void }) {
  const locked = d.can_view === false
  const server = d.mapping_type === 'server'
  return (
    <ButtonBase onClick={() => onOpen(d)} sx={(t) => ({
      justifyContent: 'flex-start', gap: 1.25, px: 1.5, py: 1, borderRadius: 2, textAlign: 'left',
      border: 1, borderColor: 'divider', backgroundColor: t.palette.background.paper,
      '&:hover': { borderColor: t.palette.primary.main },
    })}>
      <Dot d={d} />
      <Typography variant="body2" noWrap sx={{ fontWeight: 600, flexGrow: 1, minWidth: 0, color: locked ? 'text.secondary' : 'text.primary' }}>
        {d.domain}
      </Typography>
      <Box component="span" sx={(t) => ({
        fontSize: 11, fontWeight: 700, px: 0.75, borderRadius: 1,
        color: server ? 'text.secondary' : t.palette.info.main,
        backgroundColor: server ? alpha(t.palette.text.primary, 0.06) : alpha(t.palette.info.main, 0.12),
      })}>{server ? 'Server' : 'Trusted'}</Box>
      {locked && <LockOutlinedIcon sx={{ fontSize: 16, color: 'text.disabled' }} />}
    </ButtonBase>
  )
}

/* ---------------- C: Server | Trusted iki sütun, kompakt çipler ---------------- */
function TwoColumnChips({ domains, onOpen }: { domains: MappedDomain[]; onOpen: (d: MappedDomain) => void }) {
  const [q, setQ] = useState('')
  const list = domains.filter((d) => matches(d, q)).sort(mineFirst)
  const server = list.filter((d) => d.mapping_type === 'server')
  const trusted = list.filter((d) => d.mapping_type !== 'server')
  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: 'column', sm: 'row' }} sx={{ gap: 1.5, alignItems: { sm: 'center' } }}>
        <Legend />
        <Box sx={{ flexGrow: 1 }} />
        <SearchBox value={q} onChange={setQ} />
      </Stack>
      <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' } }}>
        <ChipPanel title="Server" hint="Bu sertifikayı sunan adresler" icon={<DnsOutlinedIcon />} list={server} onOpen={onOpen} />
        <ChipPanel title="Trusted" hint="Bu sertifikaya güvenen adresler" icon={<VerifiedUserOutlinedIcon />} tone="info" list={trusted} onOpen={onOpen} />
      </Box>
    </Stack>
  )
}

function Legend() {
  const items: [Tone, string][] = [['success', 'Eşleşiyor'], ['error', 'Eşleşmiyor'], ['warning', 'Uyarı']]
  return (
    <Stack direction="row" sx={{ gap: 2, flexWrap: 'wrap', alignItems: 'center' }}>
      {items.map(([tone, label]) => (
        <Stack key={label} direction="row" sx={{ gap: 0.75, alignItems: 'center' }}>
          <Box sx={(t) => ({ width: 8, height: 8, borderRadius: '50%', backgroundColor: toneColor(t, tone) })} />
          <Typography variant="caption" color="text.secondary">{label}</Typography>
        </Stack>
      ))}
      <Stack direction="row" sx={{ gap: 0.5, alignItems: 'center' }}>
        <LockOutlinedIcon sx={{ fontSize: 14, color: 'text.disabled' }} />
        <Typography variant="caption" color="text.secondary">Başka ekibin domaini</Typography>
      </Stack>
    </Stack>
  )
}

function ChipPanel({ title, hint, icon, tone = 'default', list, onOpen }: {
  title: string; hint: string; icon: React.ReactNode; tone?: Tone; list: MappedDomain[]; onOpen: (d: MappedDomain) => void
}) {
  return (
    <Box sx={{ ...CARD_SX, p: { xs: 2, md: 2.5 } }}>
      <Stack direction="row" sx={{ gap: 1.5, alignItems: 'center', mb: 2 }}>
        <IconBadge size={34} tone={tone}>{icon}</IconBadge>
        <Box sx={{ flexGrow: 1 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>{title} <Box component="span" sx={{ color: 'text.secondary', fontWeight: 600 }}>({list.length})</Box></Typography>
          <Typography variant="caption" color="text.secondary">{hint}</Typography>
        </Box>
      </Stack>
      {list.length === 0 && <Typography variant="body2" color="text.secondary">Yok</Typography>}
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, maxHeight: 360, overflowY: 'auto' }}>
        {list.map((d) => {
          const locked = d.can_view === false
          const l = live(d)
          return (
            <Tooltip key={`${d.domain_id}-${d.mapping_type}`}
                     title={`${d.team ?? 'Ekibi yok'}${locked ? ' · görüntüleme yetkiniz yok' : l ? ` · ${l.label}` : ''}`}>
              <ButtonBase onClick={() => onOpen(d)} sx={(t) => ({
                gap: 0.875, px: 1.25, py: 0.625, borderRadius: 999, border: 1, borderColor: 'divider', maxWidth: '100%',
                fontSize: 13, fontWeight: 600, color: locked ? t.palette.text.secondary : t.palette.text.primary,
                backgroundColor: locked ? alpha(t.palette.text.primary, 0.03) : t.palette.background.paper,
                '&:hover': { borderColor: t.palette.primary.main },
              })}>
                {locked ? <LockOutlinedIcon sx={{ fontSize: 14, color: 'text.disabled' }} /> : <Dot d={d} />}
                <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.domain}</Box>
              </ButtonBase>
            </Tooltip>
          )
        })}
      </Box>
    </Box>
  )
}
