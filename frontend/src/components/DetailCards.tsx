// Detay pencerelerinde (domain, sertifika) ortak kullanılan kutucuklar ve yardımcılar.
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import { Box, Button, ButtonBase, Chip, Collapse, IconButton, LinearProgress, Stack, Tooltip, Typography } from '@mui/material'
import { useSnackbar } from 'notistack'
import { type ReactNode, useState } from 'react'
import type { Certificate } from '../api/types'
import { daysLeftColor, daysLeftLabel, MONO_FONT } from '../theme'

export type Tone = 'success' | 'error' | 'warning' | 'info' | 'default'

export const GRID4 = { display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', md: 'repeat(4, 1fr)' } }
export const GRID3 = { display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', md: 'repeat(3, 1fr)' } }

export const REVOCATION: Record<string, { label: string; color: Tone }> = {
  good: { label: 'İptal edilmemiş', color: 'success' },
  revoked: { label: 'İPTAL EDİLMİŞ', color: 'error' },
  unknown: { label: 'Bilinmiyor', color: 'warning' },
  unreachable: { label: 'Ulaşılamadı', color: 'warning' },
  not_checkable: { label: 'Kontrol edilemez', color: 'default' },
  null: { label: 'Denetlenmedi', color: 'default' },
}

// DN içinden tek bir alan: dnPart("CN=X,O=Y", "O") → "Y". DN değilse CN için metnin kendisi.
export function dnPart(dn: string | null | undefined, key: string) {
  if (!dn) return null
  const m = new RegExp(`(?:^|,\\s*)${key}=([^,]+)`).exec(dn)
  if (m) return m[1]
  return key === 'CN' && !dn.includes('=') ? dn : null
}

// SAN girdisi adresi kapsıyor mu (wildcard tek seviye).
export function hostMatches(host: string, name: string) {
  const n = name.toLowerCase().replace(/^dns:/, '')
  if (n === host) return true
  return n.startsWith('*.') && host.endsWith(n.slice(1)) && !host.slice(0, -n.length + 1).includes('.')
}

export function keyText(c?: Certificate) {
  if (!c?.public_key_type) return '—'
  return [c.public_key_type, c.key_curve ?? c.key_size].filter(Boolean).join(' ')
}

export const envLabel = (e?: string | null) => (e === 'prod' ? 'Prod' : e === 'test' ? 'Test' : undefined)

export const fmtDate = (v?: string | null) => (v ? new Date(v).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' }) : '—')

type Dated = { valid_from?: string | null; valid_to?: string | null; days_left?: number | null }

// Özet sekmesinin üstündeki kart: kalan gün, bitiş, kullanılan geçerlilik süresi çubuğu.
export function ValidityCard({ cert, emptyText }: { cert?: Dated; emptyText?: string }) {
  if (!cert) {
    return (
      <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 2, p: 2.5 }}>
        <Typography variant="body2" color="text.secondary">{emptyText ?? 'Geçerlilik bilgisi yok.'}</Typography>
      </Box>
    )
  }
  const days = cert.days_left
  const color = daysLeftColor(days)
  const from = cert.valid_from ? new Date(cert.valid_from).getTime() : null
  const to = cert.valid_to ? new Date(cert.valid_to).getTime() : null
  const total = from !== null && to !== null ? Math.round((to - from) / 86_400_000) : null
  const used = from !== null && to !== null && to > from
    ? Math.min(100, Math.max(0, Math.round(((Date.now() - from) / (to - from)) * 100))) : null
  return (
    <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 2, p: 2.5 }}>
      <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'flex-start', gap: 2 }}>
        <Box>
          <Typography variant="h3" color={color === 'default' ? 'text.primary' : `${color}.main`} sx={{ fontWeight: 800, lineHeight: 1 }}>
            {days === null || days === undefined ? '—' : Math.abs(days)}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {days !== null && days !== undefined && days < 0 ? 'gün önce doldu' : 'gün kaldı'}
          </Typography>
        </Box>
        <Box sx={{ textAlign: 'right' }}>
          <Typography variant="caption" color="text.secondary">ValidTo</Typography>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>{fmtDate(cert.valid_to)}</Typography>
        </Box>
      </Stack>
      {used !== null && (
        <Box sx={{ mt: 2 }}>
          <Stack direction="row" sx={{ justifyContent: 'space-between' }}>
            <Typography variant="caption" color="text.secondary">Kullanılan geçerlilik süresi</Typography>
            <Typography variant="caption" sx={{ fontWeight: 700 }}>%{used}</Typography>
          </Stack>
          <LinearProgress variant="determinate" value={used} color={color === 'default' ? 'primary' : color}
                          sx={{ height: 8, borderRadius: 4, my: 0.75 }} />
          <Stack direction="row" sx={{ justifyContent: 'space-between' }}>
            <Typography variant="caption" color="text.secondary">ValidFrom: {fmtDate(cert.valid_from)}</Typography>
            {total !== null && <Typography variant="caption" color="text.secondary">{total} günlük geçerlilik</Typography>}
          </Stack>
        </Box>
      )}
    </Box>
  )
}

export function InfoCard({ title, value, sub, chip, color = 'default', onClick }: {
  title: string; value: ReactNode; sub?: string; chip?: { label: string; color: Tone }; color?: Tone; onClick?: () => void
}) {
  return (
    <ButtonBase component="div" disabled={!onClick} onClick={onClick}
                sx={{ display: 'block', textAlign: 'left', border: 1, borderColor: 'divider', borderRadius: 2, p: 2,
                      borderLeft: color !== 'default' ? 4 : 1, borderLeftColor: color !== 'default' ? `${color}.main` : 'divider',
                      '&:hover': onClick ? { bgcolor: 'action.hover' } : undefined }}>
      <Typography variant="overline" color="text.secondary" sx={{ lineHeight: 1.6 }}>{title}</Typography>
      <Box sx={{ typography: 'subtitle1', fontWeight: 700, wordBreak: 'break-word',
                 color: color !== 'default' ? `${color}.main` : 'text.primary' }}>{value}</Box>
      {chip && <Chip size="small" color={chip.color} label={chip.label} sx={{ mt: 0.75 }} />}
      {sub && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, wordBreak: 'break-word' }}>{sub}</Typography>}
    </ButtonBase>
  )
}

export function CopyField({ label, value }: { label: string; value?: string | null }) {
  const { enqueueSnackbar } = useSnackbar()
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Stack direction="row" spacing={0.5} sx={{ alignItems: 'flex-start' }}>
        <Typography variant="body2" sx={{ fontFamily: MONO_FONT, fontSize: 12.5, wordBreak: 'break-all', flexGrow: 1 }}>
          {value || '—'}
        </Typography>
        {value && (
          <Tooltip title="Kopyala">
            <IconButton size="small" onClick={() => { void navigator.clipboard?.writeText(value); enqueueSnackbar('Kopyalandı', { variant: 'success' }) }}>
              <ContentCopyIcon sx={{ fontSize: 16 }} />
            </IconButton>
          </Tooltip>
        )}
      </Stack>
    </Box>
  )
}

export const CERT_TYPE_FULL: Record<string, string> = {
  root: 'Root', intermediate: 'Intermediate', leaf: 'Leaf',
}

type ChainCert = Dated & {
  name: string; cert_type: string; issuer?: string | null; serial_number?: string | null
  subject_key_identifier?: string | null; is_active?: boolean
}

// Zincirdeki tek sertifikanın kutusu: kapalıyken yalnız özet (tür, ad, ValidTo, kalan gün);
// satıra tıklayınca ayrıntılar aşağı açılır, tekrar tıklayınca kapanır.
export function ChainCertCard({ index, cert, badges, actions, current, onOpen, defaultOpen = false }: {
  index?: number; cert: ChainCert; badges?: ReactNode; actions?: ReactNode; current?: boolean
  onOpen?: () => void; defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <Box sx={{ border: current ? 2 : 1, borderColor: current ? 'primary.main' : 'divider', borderRadius: 2 }}>
      <Box role="button" tabIndex={0} aria-expanded={open} onClick={() => setOpen((o) => !o)}
           onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen((o) => !o) } }}
           sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: { xs: 'wrap', md: 'nowrap' },
                 px: 1.5, py: 1.25, cursor: 'pointer', borderRadius: 2, '&:hover': { bgcolor: 'action.hover' } }}>
        <ExpandMoreIcon fontSize="small" sx={{ color: 'text.secondary', transition: 'transform 150ms',
                                               transform: open ? 'rotate(0deg)' : 'rotate(-90deg)' }} />
        <Chip size="small" variant="outlined"
              label={`${index !== undefined ? `${index}. ` : ''}${CERT_TYPE_FULL[cert.cert_type] ?? cert.cert_type}`} />
        {cert.cert_type === 'root' && <Chip size="small" color="warning" variant="outlined" label="Self-signed" />}
        {cert.is_active === false && <Chip size="small" color="warning" label="Pasif" />}
        {badges}
        <Typography variant="subtitle2" noWrap title={cert.name} sx={{ fontWeight: 700, flexGrow: 1, minWidth: 120 }}>
          {cert.name}
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
          ValidTo: {fmtDate(cert.valid_to)}
        </Typography>
        <Chip size="small" color={daysLeftColor(cert.days_left)} label={daysLeftLabel(cert.days_left)} />
        {actions && <Box onClick={(e) => e.stopPropagation()} sx={{ display: 'flex' }}>{actions}</Box>}
      </Box>
      <Collapse in={open} unmountOnExit>
        <Box sx={{ px: 2, pb: 2, pt: 0.5 }}>
          <Box sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' } }}>
            <Box>
              <Typography variant="caption" color="text.secondary">Issuer</Typography>
              <Typography variant="body2">
                {dnPart(cert.issuer, 'CN') ?? '—'}{dnPart(cert.issuer, 'O') ? ` · ${dnPart(cert.issuer, 'O')}` : ''}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">ValidFrom – ValidTo</Typography>
              <Typography variant="body2">{fmtDate(cert.valid_from)} – {fmtDate(cert.valid_to)}</Typography>
            </Box>
            <CopyField label="Serial Number" value={cert.serial_number} />
            <CopyField label="SubjectKeyIdentifier" value={cert.subject_key_identifier} />
          </Box>
          {onOpen && (
            <Button size="small" startIcon={<OpenInNewIcon fontSize="small" />} onClick={onOpen} sx={{ mt: 1 }}>
              Sertifika detayını aç
            </Button>
          )}
        </Box>
      </Collapse>
    </Box>
  )
}

export function ChainArrow() {
  return <Box sx={{ textAlign: 'center', color: 'text.disabled', lineHeight: 0, my: -0.5 }}><ArrowDownwardIcon fontSize="small" /></Box>
}

export function SectionBox({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 2, p: 2 }}>
      <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="overline" color="text.secondary">{title}</Typography>
        {action}
      </Stack>
      {children}
    </Box>
  )
}
