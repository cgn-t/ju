import ClearIcon from '@mui/icons-material/Clear'
import FilterAltOffIcon from '@mui/icons-material/FilterAltOff'
import InboxOutlinedIcon from '@mui/icons-material/InboxOutlined'
import MoreHorizIcon from '@mui/icons-material/MoreHoriz'
import SearchIcon from '@mui/icons-material/Search'
import {
  Box, Button, Chip, IconButton, InputAdornment, LinearProgress, ListItemIcon, ListItemText, Menu,
  MenuItem, Tab, Tabs, TextField, Tooltip, Typography,
} from '@mui/material'
import { alpha } from '@mui/material/styles'
import { useState, type ReactNode } from 'react'
import { daysLeftColor, daysLeftLabel } from '../theme'
import { CARD_SX, StatusPill, type Tone } from './DetailCards'

/**
 * Liste sayfalarının ortak yapı taşları — Domainler, SSL Sertifikaları, Değişiklik Talepleri,
 * Uygulamalar ve Keşif aynı düzeni kullanır: tek kart içinde (1) durum sekmeleri, (2) arama +
 * filtre satırı, (3) etkin filtre çipleri, (4) tablo, (5) sayfalama.
 */

/** Liste kartı: üstte araç çubuğu, ortada içerik, altta sayfalama — hepsi tek çerçevede. */
export function ListCard({ tabs, toolbar, chips, busy, children, footer }: {
  tabs?: ReactNode
  toolbar?: ReactNode
  chips?: ReactNode
  busy?: boolean
  children: ReactNode
  footer?: ReactNode
}) {
  return (
    <Box sx={{ ...CARD_SX, overflow: 'hidden', position: 'relative' }}>
      {tabs && <Box sx={{ px: 1.5, pt: 1.25, borderBottom: 1, borderColor: 'divider' }}>{tabs}</Box>}
      {toolbar && (
        <Box sx={{ px: 1.5, py: 1.25, display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          {toolbar}
        </Box>
      )}
      {chips && <Box sx={{ px: 1.5, pb: 1.25, mt: toolbar ? -0.25 : 1.25 }}>{chips}</Box>}
      <LinearProgress sx={{ height: 2, visibility: busy ? 'visible' : 'hidden' }} />
      {children}
      {footer && <Box sx={{ borderTop: 1, borderColor: 'divider' }}>{footer}</Box>}
    </Box>
  )
}

/** Arama kutusu — araç çubuğunda kalan genişliği doldurur. */
export function SearchBox({ value, onChange, placeholder, width = 340 }: {
  value: string
  onChange: (v: string) => void
  placeholder: string
  width?: number
}) {
  return (
    <TextField
      size="small" placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)}
      sx={{ flex: { xs: '1 1 100%', sm: `0 1 ${width}px` }, minWidth: 200 }}
      slotProps={{ input: {
        startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>,
        endAdornment: value ? (
          <InputAdornment position="end">
            <IconButton size="small" edge="end" aria-label="Aramayı temizle" onClick={() => onChange('')}>
              <ClearIcon fontSize="small" />
            </IconButton>
          </InputAdornment>
        ) : null,
      } }}
    />
  )
}

export interface StatusTabItem { value: string; label: string; count?: number; tone?: Tone }

/** Sayılı durum sekmeleri (Tümü 2000 · Geçerli 1024 · …). Etkin sekme altı çizili, sayı rozetli. */
export function StatusTabs({ value, onChange, items }: {
  value: string
  onChange: (v: string) => void
  items: StatusTabItem[]
}) {
  return (
    <Tabs value={value} onChange={(_, v) => onChange(v)} variant="scrollable" scrollButtons="auto"
          sx={{ minHeight: 40, '& .MuiTabs-indicator': { height: 2.5, borderRadius: 2 } }}>
      {items.map((t) => {
        const active = t.value === value
        return (
          <Tab key={t.value} value={t.value} disableRipple
               sx={{ minHeight: 40, px: 1.5, py: 0, minWidth: 0, textTransform: 'none', fontWeight: 600,
                     fontSize: 14, color: 'text.secondary', '&.Mui-selected': { color: 'text.primary' } }}
               label={
                 <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
                   {t.tone && t.tone !== 'default' && (
                     <Box component="span" sx={{ width: 7, height: 7, borderRadius: '50%', bgcolor: `${t.tone}.main` }} />
                   )}
                   {t.label}
                   {t.count !== undefined && (
                     <Box component="span" sx={(th) => ({
                       px: 0.75, minWidth: 22, borderRadius: 999, fontSize: 12, fontWeight: 600, lineHeight: '20px',
                       textAlign: 'center', fontVariantNumeric: 'tabular-nums',
                       bgcolor: active ? alpha(th.palette.primary.main, 0.12) : th.palette.action.hover,
                       color: active ? 'primary.main' : 'text.secondary',
                     })}>
                       {t.count.toLocaleString('tr-TR')}
                     </Box>
                   )}
                 </Box>
               } />
        )
      })}
    </Tabs>
  )
}

/** Etkin filtrelerin çipleri + "Filtreleri temizle". Boşsa hiçbir şey çizmez. */
export function ActiveFilters({ chips, onClearAll }: {
  chips: { key: string; label: string; onDelete: () => void }[]
  onClearAll?: () => void
}) {
  if (!chips.length) return null
  return (
    <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', alignItems: 'center' }}>
      <Typography variant="caption" color="text.secondary" sx={{ mr: 0.25 }}>Filtre:</Typography>
      {chips.map((c) => (
        <Chip key={c.key} size="small" label={c.label} onDelete={c.onDelete}
              sx={(t) => ({ fontWeight: 500, bgcolor: alpha(t.palette.primary.main, 0.08),
                            color: 'text.primary', border: 1, borderColor: alpha(t.palette.primary.main, 0.25) })} />
      ))}
      {onClearAll && chips.length > 1 && (
        <Button size="small" color="inherit" startIcon={<FilterAltOffIcon fontSize="small" />}
                onClick={onClearAll} sx={{ color: 'text.secondary', ml: 0.5 }}>
          Tümünü temizle
        </Button>
      )}
    </Box>
  )
}

/** Açılır/kapanır filtre çipi (ör. "Canlıda görüldü", "Pasifleri göster"). */
export function ToggleChip({ label, selected, onChange, icon }: {
  label: string
  selected: boolean
  onChange: (v: boolean) => void
  icon?: React.ReactElement
}) {
  return (
    <Chip clickable label={label} icon={icon} onClick={() => onChange(!selected)}
          aria-pressed={selected}
          variant={selected ? 'filled' : 'outlined'} color={selected ? 'primary' : 'default'}
          sx={{ fontWeight: 500, height: 32, borderRadius: 2 }} />
  )
}

/** Kalan gün: noktalı yumuşak etiket + istenirse bitiş tarihi. Boşsa sade tire. */
export function DaysLeftPill({ days, date }: { days: number | null | undefined; date?: string | null }) {
  if (days === null || days === undefined) {
    return <Typography component="span" variant="body2" color="text.disabled">—</Typography>
  }
  const c = daysLeftColor(days)
  return (
    <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 1, whiteSpace: 'nowrap' }}>
      {date && (
        <Typography component="span" variant="body2" color="text.secondary"
                    sx={{ fontVariantNumeric: 'tabular-nums', minWidth: 78 }}>
          {new Date(date).toLocaleDateString('tr-TR')}
        </Typography>
      )}
      <StatusPill size="small" tone={c === 'default' ? 'default' : c} label={daysLeftLabel(days)} />
    </Box>
  )
}

/** Satır sonu "⋯" menüsü — sık kullanılmayan/ yıkıcı işlemler burada toplanır. */
export function RowMenu({ items, label = 'Diğer işlemler' }: {
  items: { label: string; icon?: ReactNode; onClick: () => void; danger?: boolean; hidden?: boolean }[]
  label?: string
}) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const visible = items.filter((i) => !i.hidden)
  if (!visible.length) return null
  return (
    <>
      <Tooltip title={label}>
        <IconButton size="small" aria-label={label}
                    onClick={(e) => { e.stopPropagation(); setAnchor(e.currentTarget) }}
                    sx={{ color: 'text.secondary' }}>
          <MoreHorizIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)} onClick={(e) => e.stopPropagation()}
            anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
            transformOrigin={{ vertical: 'top', horizontal: 'right' }}
            slotProps={{ paper: { sx: { minWidth: 180, borderRadius: 2, border: 1, borderColor: 'divider' } } }}>
        {visible.map((i) => (
          <MenuItem key={i.label} onClick={() => { setAnchor(null); i.onClick() }}
                    sx={{ color: i.danger ? 'error.main' : undefined }}>
            {i.icon && <ListItemIcon sx={{ color: 'inherit' }}>{i.icon}</ListItemIcon>}
            <ListItemText>{i.label}</ListItemText>
          </MenuItem>
        ))}
      </Menu>
    </>
  )
}

/** Boş liste görünümü: simge + başlık + kısa açıklama + isteğe bağlı aksiyon. */
export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <Box sx={{ py: 7, px: 2, textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
      <Box sx={{ width: 52, height: 52, borderRadius: '16px', display: 'grid', placeItems: 'center',
                 bgcolor: 'action.hover', color: 'text.secondary' }}>
        <InboxOutlinedIcon />
      </Box>
      <Typography sx={{ fontWeight: 600 }}>{title}</Typography>
      {hint && <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 440 }}>{hint}</Typography>}
      {action}
    </Box>
  )
}

/** Hücrede taşmayan tek satır metin (taşarsa üç nokta + tam metin ipucu). */
export function Ellipsis({ children, max = 220, secondary }: { children: ReactNode; max?: number; secondary?: boolean }) {
  return (
    <Typography component="div" variant="body2" noWrap color={secondary ? 'text.secondary' : undefined}
                title={typeof children === 'string' ? children : undefined} sx={{ maxWidth: max }}>
      {children ?? '—'}
    </Typography>
  )
}
