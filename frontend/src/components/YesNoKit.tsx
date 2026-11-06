// Evet/Hayır alanlarının ortak gösterimi: ekranda aç/kapa listesi, düzenlerken aç/kapa anahtarı.
// Renk kuralı: Evet "yapılacak iş var" demek → mavi (info); dikkat isteyen alanlarda turuncu
// (warning). Hayır her yerde gri. Yeşil/kırmızı kullanılmaz (kırmızı süre bitişine ayrılmış).
import { Box, Stack, Switch, Typography } from '@mui/material'
import { alpha } from '@mui/material/styles'
import type { ReactNode } from 'react'
import { CARD_SX, IconBadge, toneText } from './DetailCards'

export type YesTone = 'info' | 'warning'
export const YESNO = ['Evet', 'Hayır']

const isYes = (v?: string | null) => v === 'Evet'
/** Evet/Hayır dışında eski serbest metin (ör. "Gerekirse") — anahtar yerine metin olarak gösterilir. */
export const isLegacyYesNo = (v?: string | null) => !!v && !YESNO.includes(v)

/** Salt okunur anahtar görünümü (tıklanmaz). */
function ReadOnlySwitch({ on, tone }: { on: boolean; tone: YesTone }) {
  return <Switch checked={on} size="small" color={tone} tabIndex={-1} aria-hidden sx={{ pointerEvents: 'none' }} />
}

/** Kartta tek satır: ad + değer + salt okunur anahtar (ör. sertifika Internal). */
export function YesNoValue({ value, tone = 'info' }: { value?: string | null; tone?: YesTone }) {
  if (!value) return <>—</>
  if (isLegacyYesNo(value)) return <>{value}</>
  const yes = isYes(value)
  return (
    <Stack direction="row" component="span" sx={{ alignItems: 'center', gap: 0.5 }}>
      <Box component="span" sx={(t) => ({ color: yes ? toneText(t, tone) : 'text.secondary' })}>{value}</Box>
      <ReadOnlySwitch on={yes} tone={tone} />
    </Stack>
  )
}

export interface YesNoRow { label: string; icon: ReactNode; value?: string | null; tone?: YesTone; hint?: string }

/** Tek kartta aç/kapa listesi (domain "Sertifika yenilemede yapılacaklar"). */
export function YesNoChecklist({ title, rows }: { title: string; rows: YesNoRow[] }) {
  return (
    <Box sx={{ ...CARD_SX, p: 2, gridColumn: '1 / -1' }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>{title}</Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, columnGap: 4 }}>
        {rows.map((r) => {
          const tone = r.tone ?? 'info'
          const yes = isYes(r.value)
          const legacy = isLegacyYesNo(r.value)
          return (
            <Stack key={r.label} data-testid={`yesno-${r.label}`} direction="row"
                   sx={{ alignItems: 'center', gap: 1.5, py: 1, borderBottom: 1, borderColor: 'divider' }}>
              <IconBadge tone={yes ? tone : 'default'} size={32}>{r.icon}</IconBadge>
              <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>{r.label}</Typography>
                {r.hint && yes && <Typography variant="caption" color="text.secondary">{r.hint}</Typography>}
              </Box>
              <Typography variant="body2" sx={(t) => ({ fontWeight: 700, textAlign: 'right', minWidth: 44,
                                                       color: yes ? toneText(t, tone) : 'text.secondary' })}>
                {r.value || '—'}
              </Typography>
              {!legacy && <ReadOnlySwitch on={yes} tone={tone} />}
            </Stack>
          )
        })}
      </Box>
    </Box>
  )
}

/** Düzenleme: aç/kapa anahtarı. Boş değer "Seçilmedi" gösterir; ilk tık Evet, kapatınca Hayır. */
export function YesNoSwitch({ label, value, onChange, required, tone = 'info', changed }: {
  label: string; value: string; onChange: (v: string) => void; required?: boolean; tone?: YesTone; changed?: boolean
}) {
  const yes = isYes(value)
  const missing = required && !value
  return (
    <Box>
      <Stack direction="row" sx={(t) => ({
        alignItems: 'center', justifyContent: 'space-between', border: 1, borderRadius: 1, px: 1.5, py: 0.25, minHeight: 40,
        borderColor: missing ? 'error.main' : changed ? 'info.main' : yes ? alpha(t.palette[tone].main, 0.5) : 'divider',
        bgcolor: yes ? alpha(t.palette[tone].main, t.palette.mode === 'dark' ? 0.12 : 0.06) : undefined,
      })}>
        <Typography variant="body2" sx={{ fontWeight: 500 }}>{label}{required ? ' *' : ''}</Typography>
        <Stack direction="row" sx={{ alignItems: 'center', gap: 0.5 }}>
          <Typography variant="body2" sx={(t) => ({ fontWeight: 700,
                       color: missing ? 'error.main' : yes ? toneText(t, tone) : 'text.secondary' })}>
            {value ? (yes ? 'Evet' : 'Hayır') : 'Seçilmedi'}
          </Typography>
          <Switch checked={yes} color={tone} slotProps={{ input: { 'aria-label': label } }}
                  onChange={(e) => onChange(e.target.checked ? 'Evet' : 'Hayır')} />
        </Stack>
      </Stack>
      {missing && <Typography variant="caption" color="error" sx={{ ml: 1.75 }}>Zorunlu alan, açıp kapatarak seçin</Typography>}
    </Box>
  )
}

/** Domain'in dört Evet/Hayır alanı: ad, simge, renk ve açıklama tek yerde. */
export const DOMAIN_YESNO_TONE: Record<string, YesTone> = {
  lb_update: 'info', waf_update: 'info', action_required: 'warning', ssl_pinning: 'warning',
}
