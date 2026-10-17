import CheckIcon from '@mui/icons-material/Check'
import ClearIcon from '@mui/icons-material/Clear'
import FilterAltIcon from '@mui/icons-material/FilterAlt'
import FilterAltOutlinedIcon from '@mui/icons-material/FilterAltOutlined'
import SearchIcon from '@mui/icons-material/Search'
import {
  Box, Divider, IconButton, InputAdornment, MenuItem, MenuList, Popover, TableCell,
  TextField, Tooltip, Typography,
} from '@mui/material'
import { useMemo, useState } from 'react'
import { useUrlParams, useUrlWriter } from '../hooks/useUrlState'
import { includesFolded } from '../utils/textMatch'

/**
 * Grafana benzeri kolon-başı filtre — tablo başlığındaki HUNİ ikonundan açılan popover.
 * Tek yerde tanımlı, tüm tablolarda yeniden kullanılır. İki tür kolon:
 *   • 'text'   → "içeren metin" arama kutusu (iç temizle ✕)
 *   • 'status' → sabit seçenek listesi (seçili işareti + facet kayıt sayıları)
 * Filtreleme istemci-taraflı; sayfa kendi satır listesini `matches` ile süzer.
 */

export interface StatusOpt { value: string; label: string }

export interface ColDef<T> {
  key: string
  label: string
  kind: 'text' | 'status'
  get: (row: T) => string | null | undefined  // text: aranan metin; status: satırın durum değeri
  options?: StatusOpt[]                        // kind==='status' için gerekli
  align?: 'left' | 'center' | 'right'          // başlık/gövde hizası
}

export interface ColumnFilterState<T> {
  values: Record<string, string>
  active: (key: string) => boolean
  anyActive: boolean
  clearAll: () => void
  matches: (row: T) => boolean
  defs: ColDef<T>[]
  menu: { key: string; anchor: HTMLElement } | null
  set: (key: string, value: string) => void
  open: (key: string, anchor: HTMLElement) => void
  close: () => void
}

export function useColumnFilters<T>(
  defs: ColDef<T>[], opts?: { urlPrefix?: string },
): ColumnFilterState<T> {
  const init = useMemo(
    () => Object.fromEntries(defs.map((d) => [d.key, d.kind === 'status' ? 'all' : ''])),
    [defs])
  const byKey = useMemo(() => Object.fromEntries(defs.map((d) => [d.key, d])), [defs])
  // urlPrefix verilirse değerler URL'de tutulur (?<prefix><kolon>=değer) — sayfa yenilenince /
  // bağlantı paylaşılınca filtreler korunur. Varsayılan değerler URL'ye yazılmaz.
  const prefix = opts?.urlPrefix
  const params = useUrlParams()
  const writeUrl = useUrlWriter()
  const [local, setLocal] = useState<Record<string, string>>(init)
  const values = useMemo<Record<string, string>>(
    () => prefix
      ? Object.fromEntries(defs.map((d) => [d.key, params.get(prefix + d.key) ?? init[d.key]]))
      : local,
    [prefix, params, defs, init, local])
  const write = (patch: Record<string, string>) => {
    if (!prefix) { setLocal((s) => ({ ...s, ...patch })); return }
    writeUrl((p) => {
      for (const [k, v] of Object.entries(patch)) {
        if (v === init[k] || v === undefined) p.delete(prefix + k)
        else p.set(prefix + k, v)
      }
    })
  }
  const [menu, setMenu] = useState<{ key: string; anchor: HTMLElement } | null>(null)

  const active = (key: string) =>
    byKey[key]?.kind === 'status' ? values[key] !== 'all' : !!values[key]
  const anyActive = defs.some((d) => active(d.key))
  const matches = (row: T) => defs.every((d) => {
    const v = values[d.key] ?? (d.kind === 'status' ? 'all' : '')
    if (d.kind === 'status') return v === 'all' || d.get(row) === v
    return !v || includesFolded(String(d.get(row) ?? ''), v)
  })
  return {
    values, active, anyActive, matches, defs, menu,
    set: (key, value) => write({ [key]: value }),
    clearAll: () => write(init),
    open: (key, anchor) => setMenu({ key, anchor }),
    close: () => setMenu(null),
  }
}

/** Başlık hücresi: kolon adı + huni (filtre) ikonu. Filtre aktifse dolu/renkli huni. */
export function ColHeaderCell<T>(
  { def, cf, sx }: { def: ColDef<T>; cf: ColumnFilterState<T>; sx?: object },
) {
  const on = cf.active(def.key)
  return (
    <TableCell align={def.align} sx={sx}>
      <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.25, whiteSpace: 'nowrap' }}>
        {def.label}
        <Tooltip title="Sütunu filtrele">
          <IconButton size="small" onClick={(e) => cf.open(def.key, e.currentTarget)}
                      sx={{ p: '2px', color: on ? 'primary.main' : 'text.disabled',
                            '&:hover': { color: 'primary.main' } }}>
            {on ? <FilterAltIcon sx={{ fontSize: 15 }} /> : <FilterAltOutlinedIcon sx={{ fontSize: 15 }} />}
          </IconButton>
        </Tooltip>
      </Box>
    </TableCell>
  )
}

/**
 * Tek popover (tablo başına bir tane) — açık kolonun türüne göre içerik.
 * `facetRows`: durum sayaçlarının hesaplanacağı temel satır kümesi (genelde kolon-filtresi
 * öncesi görünen liste).
 */
export function ColumnFilterMenu<T>({ cf, facetRows = [], facetCounts }: {
  cf: ColumnFilterState<T>
  facetRows?: T[]
  // Sunucu-taraflı filtrelenen tablolar için hazır sayaçlar: kolon anahtarı → {seçenek: adet}.
  // Verilen kolonda facetRows sayımı yerine bu kullanılır.
  facetCounts?: Record<string, Record<string, number>>
}) {
  const def = cf.menu ? cf.defs.find((d) => d.key === cf.menu!.key) ?? null : null
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    if (!def || def.kind !== 'status') return c
    if (facetCounts?.[def.key]) return facetCounts[def.key]
    for (const o of def.options ?? []) c[o.value] = 0
    for (const r of facetRows) {
      const v = def.get(r)
      if (v != null && c[v] !== undefined) c[v]++
    }
    c.all = facetRows.length   // 'all' seçeneği toplam sayıyı gösterir (option döngüsünden SONRA)
    return c
  }, [def, facetRows, facetCounts])

  return (
    <Popover
      open={!!cf.menu} anchorEl={cf.menu?.anchor} onClose={cf.close}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
      transformOrigin={{ vertical: 'top', horizontal: 'left' }}
      slotProps={{ paper: { sx: { mt: 0.5, borderRadius: 2, border: '1px solid',
                                  borderColor: 'divider', boxShadow: 6, overflow: 'hidden' } } }}>
      {def && (def.kind === 'text' ? (
        <Box sx={{ p: 1.5, width: 264 }}>
          <Typography variant="overline" component="div" color="text.secondary"
                      sx={{ lineHeight: 1.6, mb: 0.5 }}>{def.label}</Typography>
          <TextField
            autoFocus size="small" fullWidth placeholder="İçeren metin…"
            value={cf.values[def.key] ?? ''}
            onChange={(e) => cf.set(def.key, e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === 'Escape') cf.close() }}
            slotProps={{ input: {
              startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>,
              endAdornment: cf.values[def.key]
                ? <InputAdornment position="end">
                    <IconButton size="small" edge="end" aria-label="temizle"
                                onClick={() => cf.set(def.key, '')}>
                      <ClearIcon fontSize="small" />
                    </IconButton>
                  </InputAdornment>
                : null,
            } }} />
        </Box>
      ) : (
        <Box sx={{ minWidth: 240 }}>
          <Typography variant="overline" component="div" color="text.secondary"
                      sx={{ px: 1.5, pt: 1, pb: 0.25 }}>{def.label}</Typography>
          <Divider />
          <MenuList dense sx={{ py: 0.5 }}>
            {(def.options ?? []).map((o) => {
              const sel = (cf.values[def.key] ?? 'all') === o.value
              return (
                <MenuItem key={o.value} selected={sel} sx={{ gap: 1 }}
                          onClick={() => { cf.set(def.key, o.value); cf.close() }}>
                  <CheckIcon sx={{ fontSize: 16, color: 'primary.main', visibility: sel ? 'visible' : 'hidden' }} />
                  <Box sx={{ flexGrow: 1 }}>{o.label}</Box>
                  <Typography variant="caption" color="text.secondary"
                              sx={{ fontVariantNumeric: 'tabular-nums' }}>{counts[o.value] ?? ''}</Typography>
                </MenuItem>
              )
            })}
          </MenuList>
        </Box>
      ))}
    </Popover>
  )
}
