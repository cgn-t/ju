import DnsOutlinedIcon from '@mui/icons-material/DnsOutlined'
import LockOutlinedIcon from '@mui/icons-material/LockOutlined'
import SearchIcon from '@mui/icons-material/Search'
import VerifiedUserOutlinedIcon from '@mui/icons-material/VerifiedUserOutlined'
import { Box, ButtonBase, InputAdornment, Stack, TextField, Tooltip, Typography } from '@mui/material'
import { alpha, type Theme } from '@mui/material/styles'
import { type ReactNode, useState } from 'react'
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

/**
 * Sertifika → Bağlantılar sekmesi: bağlı domainler iki sütunda (Server | Trusted), kompakt etiketler.
 * Çok domainde kalabalık olmasın diye arama var; kendi ekibimin domainleri önce gelir;
 * başka SY ekibinin domaini kilit simgesiyle gösterilir ve tıklanınca uyarı açılır (onOpen).
 */
export default function CertificateLinksTab({ domains, onOpen }: {
  domains: MappedDomain[]; onOpen: (d: MappedDomain) => void
}) {
  if (domains.length === 0) {
    return (
      <Box sx={{ ...CARD_SX, p: 3, textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">Bu sertifika hiçbir domain'e bağlı değil</Typography>
      </Box>
    )
  }
  return <TwoColumnChips domains={domains} onOpen={onOpen} />
}

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
  title: string; hint: string; icon: ReactNode; tone?: Tone; list: MappedDomain[]; onOpen: (d: MappedDomain) => void
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
