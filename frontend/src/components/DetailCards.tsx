// Detay pencerelerinde (domain, sertifika) ortak kullanılan kutucuklar ve yardımcılar.
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutlineOutlined'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlineOutlined'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import ScheduleIcon from '@mui/icons-material/Schedule'
import { Box, Button, ButtonBase, Chip, CircularProgress, Collapse, IconButton, Stack, Tooltip, Typography } from '@mui/material'
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

const DAY = 86_400_000
const fmtDay = (t: number) => new Date(t).toLocaleDateString('tr-TR', { day: '2-digit', month: 'short', year: 'numeric' })

// Yaşam döngüsü kartı: solda kalan ömür halkası, sağda durum cümlesi ve
// ValidFrom → uyarı başlangıcı → ValidTo zaman çizelgesi (geçen süre gri, kalan güvenli süre
// yeşil, uyarı dönemi taralı). warnDays = uyarı maillerinin
// bitişten kaç gün önce başladığı (domain'in Bildirim Gün Sayısı ya da varsayılan 30).
export function ValidityCard({ cert, emptyText, warnDays = 30, warnDaysNote }: {
  cert?: Dated; emptyText?: string; warnDays?: number; warnDaysNote?: string
}) {
  if (!cert) {
    return (
      <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 2, p: 2.5 }}>
        <Typography variant="body2" color="text.secondary">{emptyText ?? 'Geçerlilik bilgisi yok.'}</Typography>
      </Box>
    )
  }
  const days = cert.days_left ?? null
  const from = cert.valid_from ? new Date(cert.valid_from).getTime() : null
  const to = cert.valid_to ? new Date(cert.valid_to).getTime() : null
  const now = Date.now()
  const span = from !== null && to !== null && to > from ? to - from : null
  const total = span !== null ? Math.round(span / DAY) : null
  const pos = (t: number) => (span === null || from === null ? 0 : Math.min(100, Math.max(0, ((t - from) / span) * 100)))
  const warnAt = to !== null ? to - warnDays * DAY : null
  const remainingPct = span !== null && to !== null ? Math.min(100, Math.max(0, ((to - now) / span) * 100)) : 0

  const state: 'ok' | 'warn' | 'expired' | 'unknown' =
    days === null ? 'unknown' : days < 0 ? 'expired' : days <= warnDays ? 'warn' : 'ok'
  const tone = state === 'ok' ? 'success' : state === 'warn' ? 'warning' : state === 'expired' ? 'error' : 'info'
  const headline = state === 'ok' ? 'Geçerli — şu an işlem gerekmiyor'
    : state === 'warn' ? 'Yenileme dönemi — uyarı mailleri gönderiliyor'
      : state === 'expired' ? 'Süresi dolmuş — sertifika yenilenmeli' : 'Geçerlilik bilinmiyor'
  const StateIcon = state === 'ok' ? CheckCircleOutlineIcon : state === 'warn' ? ScheduleIcon : ErrorOutlineIcon
  const warnLine = warnAt === null ? null
    : state === 'ok' ? `Uyarı mailleri ${fmtDay(warnAt)} tarihinde başlayacak (${Math.max(0, Math.ceil((warnAt - now) / DAY))} gün sonra)`
      : state === 'warn' ? `Uyarı mailleri ${fmtDay(warnAt)} tarihinde başladı`
        : `Süre ${fmtDay(to!)} tarihinde doldu`

  return (
    <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 2, p: { xs: 2, md: 2.5 },
               display: 'grid', gap: { xs: 2, md: 3 }, alignItems: 'center',
               gridTemplateColumns: { xs: '1fr', sm: 'auto 1fr' } }}>
      {/* Kalan ömür halkası */}
      <Box sx={{ position: 'relative', width: 128, height: 128, justifySelf: 'center' }}>
        <CircularProgress variant="determinate" value={100} size={128} thickness={3.2}
                          sx={{ color: 'action.hover', position: 'absolute', inset: 0 }} />
        <CircularProgress variant="determinate" value={state === 'expired' ? 100 : remainingPct} size={128} thickness={3.2}
                          color={tone} sx={{ position: 'absolute', inset: 0, '& circle': { strokeLinecap: 'round' } }} />
        <Box sx={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
                   alignItems: 'center', justifyContent: 'center', textAlign: 'center' }}>
          <Typography sx={{ fontSize: 30, fontWeight: 800, lineHeight: 1, color: `${tone}.main` }}>
            {days === null ? '—' : Math.abs(days)}
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 0.25 }}>
            {days !== null && days < 0 ? 'gün geçti' : 'gün kaldı'}
          </Typography>
        </Box>
      </Box>

      <Box sx={{ minWidth: 0 }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <StateIcon fontSize="small" color={tone} />
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{headline}</Typography>
        </Stack>
        {warnLine && (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
            {warnLine}{warnDaysNote ? ` · ${warnDaysNote}` : ''}
          </Typography>
        )}

        {span !== null && warnAt !== null && (
          <Box sx={{ mt: 2.5 }}>
            {/* Zaman çizelgesi: geçen süre (koyu), kalan güvenli süre, uyarı dönemi (taralı) */}
            <Box sx={{ position: 'relative', height: 10, borderRadius: 5, bgcolor: 'action.hover', overflow: 'visible' }}>
              <Box sx={{ position: 'absolute', left: `${pos(warnAt)}%`, right: 0, top: 0, bottom: 0,
                         borderTopRightRadius: 5, borderBottomRightRadius: 5,
                         backgroundImage: (t) => `repeating-linear-gradient(135deg, ${t.palette.warning.main}55 0 6px, transparent 6px 12px)` }} />
              {state === 'ok' && (
                <Box sx={{ position: 'absolute', left: `${pos(now)}%`, width: `${Math.max(0, pos(warnAt) - pos(now))}%`,
                           top: 0, bottom: 0, bgcolor: 'success.main', opacity: 0.35 }} />
              )}
              <Box sx={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${pos(now)}%`,
                         borderRadius: 5, bgcolor: state === 'expired' ? 'error.main' : 'text.disabled' }} />
              {state !== 'expired' && (
                <Tooltip title={`Bugün · %${Math.round(100 - remainingPct)} kullanıldı`}>
                  <Box sx={{ position: 'absolute', left: `${pos(now)}%`, top: -5, width: 4, height: 20,
                             ml: '-2px', borderRadius: 2, bgcolor: 'text.primary', border: 2, borderColor: 'background.paper' }} />
                </Tooltip>
              )}
            </Box>
            <Box sx={{ position: 'relative', height: 40, mt: 0.75 }}>
              <TimelineLabel align="left" title="ValidFrom" value={fmtDay(from!)} />
              {pos(warnAt) > 18 && pos(warnAt) < 82 && (
                <TimelineLabel align="center" at={pos(warnAt)} title={`Uyarı (${warnDays} gün önce)`} value={fmtDay(warnAt)} />
              )}
              <TimelineLabel align="right" title="ValidTo" value={fmtDay(to!)} />
            </Box>
            <Stack direction="row" useFlexGap sx={{ flexWrap: 'wrap', columnGap: 3, rowGap: 0.5, mt: 0.5 }}>
              <Stat label="Toplam ömür" value={`${total} gün`} />
              <Stat label="Geçen" value={`${Math.max(0, Math.round((Math.min(now, to!) - from!) / DAY))} gün`} />
              <Stat label="Kullanılan" value={`%${Math.round(100 - remainingPct)}`} />
            </Stack>
          </Box>
        )}
      </Box>
    </Box>
  )
}

function TimelineLabel({ align, at, title, value }: { align: 'left' | 'center' | 'right'; at?: number; title: string; value: string }) {
  const pos = align === 'left' ? { left: 0 } : align === 'right' ? { right: 0, textAlign: 'right' as const }
    : { left: `${at}%`, transform: 'translateX(-50%)', textAlign: 'center' as const }
  return (
    <Box sx={{ position: 'absolute', top: 0, whiteSpace: 'nowrap', ...pos }}>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.3 }}>{title}</Typography>
      <Typography variant="body2" sx={{ fontWeight: 600, lineHeight: 1.3 }}>{value}</Typography>
    </Box>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Typography variant="caption" color="text.secondary">
      {label}: <Box component="span" sx={{ color: 'text.primary', fontWeight: 700 }}>{value}</Box>
    </Typography>
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
