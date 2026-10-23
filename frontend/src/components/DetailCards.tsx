// Detay pencerelerinde (domain, sertifika) ortak kullanılan kutucuklar ve yardımcılar.
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutlineOutlined'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import CloseIcon from '@mui/icons-material/Close'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlineOutlined'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import ScheduleIcon from '@mui/icons-material/Schedule'
import { Box, Button, ButtonBase, CircularProgress, Collapse, IconButton, Stack, Tab, Tabs, Tooltip, Typography } from '@mui/material'
import { alpha, type Theme } from '@mui/material/styles'
import { useSnackbar } from 'notistack'
import { type ReactElement, type ReactNode, useState } from 'react'
import type { Certificate, CertExtras } from '../api/types'
import { daysLeftColor, daysLeftLabel, MONO_FONT, nodeColors } from '../theme'

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
      <Box sx={{ ...CARD_SX, p: 2.5 }}>
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
    <Box sx={(t) => ({ ...CARD_SX, p: { xs: 2, md: 3 },
               background: `linear-gradient(120deg, ${alpha(tone === 'info' ? t.palette.info.main : t.palette[tone].main, t.palette.mode === 'dark' ? 0.12 : 0.07)} 0%, ${t.palette.background.paper} 45%)`,
               display: 'grid', gap: { xs: 2, md: 3 }, alignItems: 'center',
               gridTemplateColumns: { xs: '1fr', sm: 'auto 1fr' } })}>
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
  // Dar ekranda ortadaki (uyarı) etiketi kenar etiketleriyle çakışır: telefonda gizlenir.
  return (
    <Box sx={{ position: 'absolute', top: 0, whiteSpace: 'nowrap', ...pos,
               display: align === 'center' ? { xs: 'none', sm: 'block' } : 'block' }}>
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

// Durum rengi: metin için açık temada koyu ton, koyu temada açık ton (okunabilirlik).
export function toneText(t: Theme, tone: Tone) {
  if (tone === 'default') return t.palette.text.secondary
  return t.palette.mode === 'dark' ? t.palette[tone].light : t.palette[tone].dark
}
const toneMain = (t: Theme, tone: Tone) => (tone === 'default' ? t.palette.text.secondary : t.palette[tone].main)

// Yuvarlatılmış kare simge zemini; tona göre hafif renkli. color verilirse tonu ezer (ör. sertifika türü rengi).
export function IconBadge({ children, tone = 'default', color, size = 36 }: {
  children: ReactNode; tone?: Tone; color?: string; size?: number
}) {
  return (
    <Box sx={(t) => {
      const c = color ?? toneMain(t, tone)
      return {
        width: size, height: size, flexShrink: 0, borderRadius: `${Math.round(size * 0.3)}px`,
        display: 'grid', placeItems: 'center',
        bgcolor: tone === 'default' && !color ? t.palette.action.hover : alpha(c, t.palette.mode === 'dark' ? 0.2 : 0.12),
        color: color ?? toneText(t, tone),
        '& svg': { fontSize: size * 0.55 },
      }
    }}>
      {children}
    </Box>
  )
}

// Noktalı durum etiketi (dolu Chip yerine yumuşak zemin).
export function StatusPill({ tone, label, size = 'medium' }: { tone: Tone; label: ReactNode; size?: 'small' | 'medium' }) {
  return (
    <Box component="span" sx={(t) => ({
      display: 'inline-flex', alignItems: 'center', gap: 0.75, whiteSpace: 'nowrap',
      px: size === 'small' ? 1 : 1.25, py: size === 'small' ? 0.125 : 0.25, borderRadius: 999,
      fontSize: size === 'small' ? 12 : 12.5, fontWeight: 600, lineHeight: 1.6,
      color: toneText(t, tone),
      bgcolor: tone === 'default' ? t.palette.action.hover : alpha(toneMain(t, tone), t.palette.mode === 'dark' ? 0.18 : 0.1),
      border: 1, borderColor: tone === 'default' ? t.palette.divider : alpha(toneMain(t, tone), 0.25),
    })}>
      <Box component="span" sx={(t) => ({ width: 7, height: 7, borderRadius: '50%', bgcolor: toneMain(t, tone), flexShrink: 0 })} />
      {label}
    </Box>
  )
}

export const CARD_SX = {
  bgcolor: 'background.paper', border: 1, borderColor: 'divider', borderRadius: '14px',
} as const

export function InfoCard({ title, value, sub, chip, color = 'default', icon, onClick }: {
  title: string; value: ReactNode; sub?: string; chip?: { label: string; color: Tone }; color?: Tone
  icon?: ReactNode; onClick?: () => void
}) {
  return (
    <ButtonBase component="div" disabled={!onClick} onClick={onClick}
                sx={(t) => ({ ...CARD_SX, display: 'flex', gap: 1.5, alignItems: 'flex-start', textAlign: 'left', p: 2,
                      transition: 'border-color 150ms, box-shadow 150ms, transform 150ms',
                      '&:hover': onClick ? { borderColor: alpha(t.palette.primary.main, 0.45), transform: 'translateY(-1px)',
                                             boxShadow: `0 6px 18px ${alpha('#000', t.palette.mode === 'dark' ? 0.35 : 0.07)}`,
                                             '& .info-go': { opacity: 1 } } : undefined })}>
      {icon && <IconBadge tone={color}>{icon}</IconBadge>}
      <Box sx={{ minWidth: 0, flexGrow: 1 }}>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', fontWeight: 500, lineHeight: 1.5 }}>{title}</Typography>
        <Box sx={(t) => ({ typography: 'body1', fontWeight: 650, lineHeight: 1.35, wordBreak: 'break-word', mt: 0.25,
                   color: color !== 'default' ? toneText(t, color) : 'text.primary' })}>{value}</Box>
        {chip && <Box sx={{ mt: 0.75 }}><StatusPill size="small" tone={chip.color} label={chip.label} /></Box>}
        {sub && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, wordBreak: 'break-word', lineHeight: 1.4 }}>{sub}</Typography>}
      </Box>
      {onClick && <ChevronRightIcon className="info-go" fontSize="small" sx={{ color: 'text.disabled', opacity: 0.5, transition: 'opacity 150ms', mt: 0.25 }} />}
    </ButtonBase>
  )
}

// Kutucuk grubu başlığı: kartların üstünde sade başlık + sağda kısa açıklama.
export function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <Box>
      <Stack direction="row" sx={{ alignItems: 'baseline', justifyContent: 'space-between', mb: 1.25, gap: 1 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700, letterSpacing: '0.01em' }}>{title}</Typography>
        {aside && <Typography variant="caption" color="text.secondary">{aside}</Typography>}
      </Stack>
      {children}
    </Box>
  )
}

function copyText(value: string, notify: (m: string) => void) {
  void navigator.clipboard?.writeText(value)
  notify('Kopyalandı')
}

// Etiket | değer | kopyala satırlarından oluşan liste (Serial Number, Fingerprint, SPKI Pin …).
export function PropList({ title, rows }: { title?: string; rows: { label: string; value?: string | null; mono?: boolean }[] }) {
  const { enqueueSnackbar } = useSnackbar()
  const notify = (m: string) => enqueueSnackbar(m, { variant: 'success' })
  return (
    <Box sx={{ ...CARD_SX, overflow: 'hidden' }}>
      {title && (
        <Typography variant="subtitle2" sx={{ fontWeight: 700, px: 2, py: 1.5, borderBottom: 1, borderColor: 'divider' }}>{title}</Typography>
      )}
      {rows.map((r, i) => (
        <Box key={r.label} sx={{ display: 'grid', alignItems: 'center', columnGap: 2, rowGap: 0.25, px: 2, py: 1.1,
                                 gridTemplateColumns: { xs: '1fr auto', md: '200px 1fr auto' },
                                 borderTop: i ? 1 : 0, borderColor: 'divider',
                                 '&:hover': { bgcolor: 'action.hover' } }}>
          <Typography variant="body2" color="text.secondary" sx={{ gridColumn: { xs: '1 / -1', md: 'auto' } }}>{r.label}</Typography>
          <Typography variant="body2" sx={{ fontFamily: r.mono === false ? undefined : MONO_FONT, fontSize: r.mono === false ? undefined : 12.5,
                                            wordBreak: 'break-all', minWidth: 0 }}>
            {r.value || '—'}
          </Typography>
          <Box sx={{ width: 30, height: 30 }}>
            {r.value && (
              <Tooltip title="Kopyala">
                <IconButton size="small" aria-label={`${r.label} kopyala`} onClick={() => copyText(r.value!, notify)}>
                  <ContentCopyIcon sx={{ fontSize: 16 }} />
                </IconButton>
              </Tooltip>
            )}
          </Box>
        </Box>
      ))}
    </Box>
  )
}

export function CopyField({ label, value }: { label: string; value?: string | null }) {
  const { enqueueSnackbar } = useSnackbar()
  return (
    <Box sx={{ minWidth: 0 }}>
      {label && <Typography variant="caption" color="text.secondary">{label}</Typography>}
      <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center', bgcolor: 'action.hover', borderRadius: '8px', pl: 1, pr: 0.25, py: 0.25, mt: 0.25 }}>
        <Typography variant="body2" sx={{ fontFamily: MONO_FONT, fontSize: 12.5, wordBreak: 'break-all', flexGrow: 1 }}>
          {value || '—'}
        </Typography>
        {value && (
          <Tooltip title="Kopyala">
            <IconButton size="small" onClick={() => copyText(value, (m) => enqueueSnackbar(m, { variant: 'success' }))}>
              <ContentCopyIcon sx={{ fontSize: 16 }} />
            </IconButton>
          </Tooltip>
        )}
      </Stack>
    </Box>
  )
}

// Detay penceresinin başlık bandı: duruma göre hafif renkli zemin, simge, ad, durum ve sekmeler.
export function DetailHeader({ icon, iconColor, tone, title, titleExtra, meta, actions, onClose, tabs }: {
  icon: ReactNode; iconColor?: string; tone: Tone; title: ReactNode; titleExtra?: ReactNode
  meta?: ReactNode; actions?: ReactNode; onClose: () => void; tabs?: ReactNode
}) {
  return (
    <Box sx={(t) => ({
      px: { xs: 2, md: 3 }, pt: { xs: 2, md: 2.5 }, pb: 2, borderBottom: 1, borderColor: 'divider',
      backgroundColor: t.palette.background.paper,
      backgroundImage: `linear-gradient(135deg, ${alpha(toneMain(t, tone), t.palette.mode === 'dark' ? 0.16 : 0.09)} 0%, ${alpha(toneMain(t, tone), 0)} 55%)`,
    })}>
      <Stack direction="row" sx={{ alignItems: 'center', gap: 2 }}>
        <Box sx={{ display: { xs: 'none', sm: 'block' } }}><IconBadge size={48} tone={tone} color={iconColor}>{icon}</IconBadge></Box>
        <Box sx={{ minWidth: 0, flexGrow: 1 }}>
          <Stack direction="row" sx={{ alignItems: 'center', gap: 0.5, minWidth: 0 }}>
            <Typography variant="h5" component="h2" noWrap sx={{ fontWeight: 700, fontSize: { xs: 19, md: 22 }, minWidth: 0 }}>
              {title}
            </Typography>
            {titleExtra}
          </Stack>
          {meta && (
            <Stack direction="row" useFlexGap sx={{ alignItems: 'center', flexWrap: 'wrap', columnGap: 1.25, rowGap: 0.75, mt: 0.75 }}>
              {meta}
            </Stack>
          )}
        </Box>
        {actions && <Box sx={{ display: { xs: 'none', sm: 'flex' }, gap: 1, flexShrink: 0 }}>{actions}</Box>}
        <IconButton aria-label="Kapat" onClick={onClose} sx={{ alignSelf: 'flex-start', mt: -0.5, mr: -1 }}>
          <CloseIcon />
        </IconButton>
      </Stack>
      {tabs && <Box sx={{ mt: 2.25 }}>{tabs}</Box>}
    </Box>
  )
}

// Başlıktaki kısa bilgi: "ValidTo 25 Şub 2027" gibi; aralarında ince ayraç.
export function MetaItem({ label, value }: { label?: string; value: ReactNode }) {
  return (
    <Typography variant="body2" color="text.secondary" component="span" sx={{ whiteSpace: 'nowrap' }}>
      <Box component="span" aria-hidden sx={{ color: 'text.disabled', mr: 1.25 }}>•</Box>
      {label && <>{label} </>}<Box component="span" sx={{ color: 'text.primary', fontWeight: 600 }}>{value}</Box>
    </Typography>
  )
}

// Hap şeklinde sekmeler; seçili sekme beyaz zeminli. Telefonda yatay kayar.
export function DetailTabs<T extends string>({ value, onChange, items, scrollable }: {
  value: T; onChange: (v: T) => void; scrollable?: boolean
  items: { value: T; label: string; icon?: ReactElement; count?: number }[]
}) {
  return (
    <Tabs value={value} onChange={(_, v: T) => onChange(v)} variant={scrollable ? 'scrollable' : 'standard'} scrollButtons={false}
          sx={(t) => ({
            minHeight: 0, width: scrollable ? '100%' : 'fit-content', maxWidth: '100%', p: 0.5, borderRadius: '12px',
            bgcolor: alpha(t.palette.text.primary, t.palette.mode === 'dark' ? 0.08 : 0.05),
            '& .MuiTabs-indicator': { display: 'none' },
            '& .MuiTabs-flexContainer, & .MuiTabs-list': { gap: 0.5 },
            '& .MuiTab-root': { minHeight: 36, minWidth: 0, px: 1.75, py: 0.75, borderRadius: '9px', textTransform: 'none',
                                fontWeight: 600, fontSize: 14, color: 'text.secondary', transition: 'background-color 150ms, color 150ms',
                                '&:hover': { color: 'text.primary' } },
            '& .MuiTab-root .MuiTab-icon': { mr: 0.75, mb: 0, fontSize: 18 },
            '& .MuiTab-root.Mui-selected': { color: 'text.primary', bgcolor: 'background.paper',
                                             boxShadow: `0 1px 3px ${alpha('#000', 0.14)}, 0 0 0 1px ${alpha('#000', t.palette.mode === 'dark' ? 0.3 : 0.04)}` },
          })}>
      {items.map((i) => (
        <Tab key={i.value} value={i.value} icon={i.icon} iconPosition="start"
             label={<Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
               {i.label}
               {i.count !== undefined && (
                 <Box component="span" sx={{ minWidth: 20, px: 0.6, borderRadius: 999, fontSize: 11.5, lineHeight: '18px',
                                             bgcolor: 'action.selected', color: 'text.secondary', textAlign: 'center' }}>{i.count}</Box>
               )}
             </Box>} />
      ))}
    </Tabs>
  )
}

// Detay pencereleri için ortak Dialog kağıdı: yuvarlak köşe, gövde gri zemin.
export const DIALOG_PAPER_SX = { height: { md: '88vh' }, borderRadius: { xs: 0, sm: '20px' }, overflow: 'hidden', bgcolor: 'background.default' }
export const DIALOG_BODY_SX = { pt: '20px !important', px: { xs: 2, md: 3 }, pb: 3, bgcolor: 'background.default' }

export const CERT_TYPE_FULL: Record<string, string> = {
  root: 'Root', intermediate: 'Intermediate', leaf: 'Leaf',
}

type ChainCert = Dated & {
  name: string; cert_type: string; issuer?: string | null; serial_number?: string | null
  subject_key_identifier?: string | null; is_active?: boolean
}

const TYPE_LETTER: Record<string, string> = { root: 'R', intermediate: 'I', leaf: 'L' }

// Zincirdeki tek sertifikanın kutusu: kapalıyken yalnız özet (tür, ad, ValidTo, kalan gün);
// satıra tıklayınca ayrıntılar aşağı açılır, tekrar tıklayınca kapanır.
export function ChainCertCard({ index, cert, badges, actions, current, onOpen, defaultOpen = false }: {
  index?: number; cert: ChainCert; badges?: ReactNode; actions?: ReactNode; current?: boolean
  onOpen?: () => void; defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const typeLabel = CERT_TYPE_FULL[cert.cert_type] ?? cert.cert_type
  const typeColor = nodeColors[cert.cert_type] ?? '#9e9e9e'
  return (
    <Box sx={(t) => ({ ...CARD_SX, borderColor: current ? alpha(t.palette.primary.main, 0.6) : 'divider',
                       boxShadow: current ? `0 0 0 3px ${alpha(t.palette.primary.main, 0.12)}` : 'none' })}>
      <Box role="button" tabIndex={0} aria-expanded={open} onClick={() => setOpen((o) => !o)}
           onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen((o) => !o) } }}
           sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: { xs: 'wrap', md: 'nowrap' },
                 px: 1.5, py: 1.25, cursor: 'pointer', borderRadius: '14px', '&:hover': { bgcolor: 'action.hover' } }}>
        <IconBadge color={typeColor}>
          <Typography component="span" sx={{ fontWeight: 800, fontSize: 15, lineHeight: 1 }}>{TYPE_LETTER[cert.cert_type] ?? '?'}</Typography>
        </IconBadge>
        <Box sx={{ minWidth: 140, flexGrow: 1 }}>
          <Typography variant="subtitle2" noWrap title={cert.name} sx={{ fontWeight: 700 }}>{cert.name}</Typography>
          <Typography variant="caption" color="text.secondary" noWrap sx={{ display: 'block' }}>
            {index !== undefined ? `${index}. ` : ''}{typeLabel}
            {cert.cert_type === 'root' ? ' · Self-signed' : cert.issuer ? ` · Issuer: ${dnPart(cert.issuer, 'CN') ?? cert.issuer}` : ''}
          </Typography>
        </Box>
        {cert.is_active === false && <StatusPill size="small" tone="warning" label="Pasif" />}
        {badges}
        <Box sx={{ textAlign: 'right', display: { xs: 'none', sm: 'block' } }}>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.2 }}>ValidTo</Typography>
          <Typography variant="body2" sx={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{fmtDay(new Date(cert.valid_to ?? 0).getTime())}</Typography>
        </Box>
        <StatusPill size="small" tone={daysTone(cert.days_left)} label={daysLeftLabel(cert.days_left)} />
        {actions && <Box onClick={(e) => e.stopPropagation()} sx={{ display: 'flex' }}>{actions}</Box>}
        <ExpandMoreIcon fontSize="small" sx={{ color: 'text.secondary', transition: 'transform 150ms',
                                               transform: open ? 'rotate(180deg)' : 'rotate(0deg)' }} />
      </Box>
      <Collapse in={open} unmountOnExit>
        <Box sx={{ px: 2, pb: 2, pt: 1, borderTop: 1, borderColor: 'divider' }}>
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
            <Button size="small" startIcon={<OpenInNewIcon fontSize="small" />} onClick={onOpen} sx={{ mt: 1.25 }}>
              Sertifika detayını aç
            </Button>
          )}
        </Box>
      </Collapse>
    </Box>
  )
}

const daysTone = (d?: number | null): Tone => { const c = daysLeftColor(d); return c === 'default' ? 'default' : c }

// Zincir kartları arasındaki bağlantı çizgisi (rozetlerin hizasında).
export function ChainArrow() {
  return <Box aria-hidden sx={{ ml: '30px', width: 2, height: 14, bgcolor: 'divider', borderRadius: 1 }} />
}

export function SectionBox({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <Box sx={{ ...CARD_SX, p: { xs: 2, md: 2.5 } }}>
      <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1.5, minHeight: 28 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>{title}</Typography>
        {action}
      </Stack>
      {children}
    </Box>
  )
}

export const VALIDATION_LABEL: Record<string, string> = {
  EV: 'EV — kurumun kimliği ayrıntılı doğrulanmış (Extended Validation)',
  OV: 'OV — kurum doğrulanmış (Organization Validation)',
  DV: 'DV — yalnız alan adı sahipliği doğrulanmış (Domain Validation)',
  IV: 'IV — kişi doğrulanmış (Individual Validation)',
}

export function basicConstraintsText(e?: CertExtras | null) {
  if (!e || e.basic_constraints_ca === null || e.basic_constraints_ca === undefined) return '—'
  if (!e.basic_constraints_ca) return 'CA:FALSE'
  return `CA:TRUE${e.basic_constraints_path_length !== null && e.basic_constraints_path_length !== undefined ? `, pathLen:${e.basic_constraints_path_length}` : ''}`
}

// OCSP / CRL / CA Issuers adres listesi (kopyalanabilir). Kapalı ağda hangi adrese izin
// verilmesi gerektiğini görmek için.
export function UrlList({ label, urls }: { label: string; urls: string[] }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      {urls.length === 0 ? <Typography variant="body2">—</Typography> : urls.map((u) => (
        <Box key={u}><CopyField label="" value={u} /></Box>
      ))}
    </Box>
  )
}

export function RevocationEndpoints({ extras }: { extras?: CertExtras | null }) {
  if (!extras) return null
  return (
    <SectionBox title="İptal kontrol adresleri">
      <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr 1fr' } }}>
        <UrlList label="OCSP" urls={extras.ocsp_urls} />
        <UrlList label="CRL Distribution Points" urls={extras.crl_urls} />
        <UrlList label="CA Issuers" urls={extras.ca_issuers_urls} />
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
        İptal Durumu "Ulaşılamadı" görünüyorsa, Jumbo sunucusunun bu adreslere (genelde http/80) erişimine izin verilmesi gerekir.
      </Typography>
    </SectionBox>
  )
}
