import FileDownloadIcon from '@mui/icons-material/FileDownload'
import HistoryIcon from '@mui/icons-material/History'
import RefreshIcon from '@mui/icons-material/Refresh'
import SearchIcon from '@mui/icons-material/Search'
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined'
import {
  Alert, Box, Button, Chip, IconButton, InputAdornment, LinearProgress, Stack, Tab, Table, TableBody,
  TableCell, TableHead, TablePagination, TableRow, Tabs, TextField, Tooltip, Typography,
} from '@mui/material'
import { alpha } from '@mui/material/styles'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useMemo, useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { AuditCategory, AuditEntry, AuditFacets, AuditList, AuditMeta } from '../api/types'
import { useUrlId, useUrlPatch, useUrlState } from '../hooks/useUrlState'
import { MONO_FONT } from '../theme'
import ApplicationDetailDrawer from './ApplicationDetailDrawer'
import AuditDetailDrawer from './AuditDetailDrawer'
import { formatAuditTime, formatLocalInput, presetHours, relativeTime, TIME_PRESETS, type TimePreset } from '../utils/auditFormat'
import ActionDot from './AuditActionDot'
import CertificateDetailDrawer from './CertificateDetailDrawer'
import { ColHeaderCell, ColumnFilterMenu, useColumnFilters, type ColDef } from './ColumnFilters'
import DomainDetailDrawer from './DomainDetailDrawer'
import TimeRangePicker from './TimeRangePicker'

/**
 * Audit Log — kurumsal denetim ekranı. Filtreler SUNUCUDA uygulanır (liste filtreye uyan en
 * yeni 1000 kayıt); kolon başlıklarındaki huni menüleri ColumnFilters'ın durumunu kullanır,
 * süzme yapmaz — değerler sorgu parametresine çevrilir. CSV aynı parametrelerle tüm aralığı indirir.
 */

type Tab_ = 'all' | AuditCategory
const CATEGORY_TABS: AuditCategory[] = ['changes', 'approval', 'security', 'system']
const NOOP = () => null  // sunucu-taraflı filtre: ColDef.get kullanılmaz

function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

function UserCell({ username, fullName }: { username: string; fullName?: string | null }) {
  const automated = username === 'system' || username === 'external-api'
  if (!automated && fullName) {
    return (
      <Tooltip title={`${fullName} (${username})`} placement="top-start">
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body2" noWrap sx={{ fontWeight: 500 }}>{fullName}</Typography>
          <Typography variant="caption" color="text.secondary" noWrap component="div">{username}</Typography>
        </Box>
      </Tooltip>
    )
  }
  if (!automated) return <Typography variant="body2" noWrap>{username}</Typography>
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, color: 'text.secondary' }}>
      <SmartToyOutlinedIcon sx={{ fontSize: 15 }} />
      <Typography variant="body2" noWrap color="text.secondary">
        {username === 'system' ? 'Sistem' : 'Dış API'}
      </Typography>
    </Box>
  )
}

export default function AuditLogPanel() {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [tab, setTab] = useUrlState<Tab_>('audit_tab', 'all', ['all', ...CATEGORY_TABS])
  // Tüm görünüm durumu URL'de (audit_*) — yenileyince/bağlantı paylaşınca aynı ekran açılır
  const [search, setSearch] = useUrlState<string>('audit_q', '')
  // Özel (mutlak) aralık: datetime-local, İstanbul saati — Grafana tarzı seçiciden
  const [dateFrom] = useUrlState<string>('audit_from', '')
  const [dateTo] = useUrlState<string>('audit_to', '')
  const [histTable] = useUrlState<string>('audit_hist_t', '')
  const [histId] = useUrlState<string>('audit_hist_id', '')
  const [selectedId, setSelectedId] = useUrlId('audit_entry')
  const patchUrl = useUrlPatch()
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(50)
  const [openRecord, setOpenRecord] = useState<{ table: string; id: number } | null>(null)

  const { data: meta } = useQuery<AuditMeta>({
    queryKey: ['audit-meta'],
    queryFn: async () => (await api.get('/audit/meta')).data,
    staleTime: Infinity,
  })

  // ---- Kolon filtreleri (durum = useColumnFilters; süzme sunucuda) ----
  const [facetsForDefs, setFacetsForDefs] = useState<AuditFacets | undefined>()
  const defs = useMemo<ColDef<AuditEntry>[]>(() => [
    // Huni menüsünde yalnız hızlı aralıklar; özel aralık araç çubuğundaki seçiciden girilir
    { key: 'time', label: 'Zaman', kind: 'status', options: TIME_PRESETS.filter((p) => p.value !== 'custom'), get: NOOP },
    { key: 'user', label: 'Kullanıcı', kind: 'text', get: NOOP },
    { key: 'action', label: 'İşlem', kind: 'status', get: NOOP, options: [
      { value: 'all', label: 'Tümü' },
      ...(facetsForDefs?.actions ?? []).map((a) => ({ value: a.value, label: meta?.actions[a.value] ?? a.value })),
    ] },
    { key: 'table', label: 'Nesne', kind: 'status', get: NOOP, options: [
      { value: 'all', label: 'Tümü' },
      ...(facetsForDefs?.tables ?? []).map((t) => ({ value: t.value, label: meta?.tables[t.value] ?? t.value })),
    ] },
    { key: 'record', label: 'Kayıt', kind: 'text', get: NOOP },
    { key: 'details', label: 'Değişiklik', kind: 'text', get: NOOP },
    { key: 'ip', label: 'IP', kind: 'text', get: NOOP },
  ], [facetsForDefs, meta])
  const cf = useColumnFilters(defs, { urlPrefix: 'audit_f_' })
  const v = cf.values
  const preset = (TIME_PRESETS.some((p) => p.value === v.time) ? v.time : 'all') as TimePreset
  // Özel aralıktan çıkılınca (menüden ya da başlık hunisinden) eski tarihler URL'de kalmasın
  useEffect(() => {
    if (preset !== 'custom' && (dateFrom || dateTo)) patchUrl({ audit_from: null, audit_to: null })
  }, [preset])  // eslint-disable-line react-hooks/exhaustive-deps

  // Zaman: hızlı aralık → since_hours (kayan pencere); özel → start/end (mutlak, saatli)
  const sinceHours = presetHours(preset)
  const start = preset === 'custom' ? dateFrom || undefined : undefined
  const end = preset === 'custom' ? dateTo || undefined : undefined
  const changeTime = (p: TimePreset, f?: string, t?: string) => patchUrl({
    audit_f_time: p === 'all' ? null : p,
    audit_from: p === 'custom' ? (f ?? null) : null,
    audit_to: p === 'custom' ? (t || null) : null,
  })
  const dq = useDebounced({ search, user: v.user, record: v.record, details: v.details, ip: v.ip })

  const params = {
    category: tab === 'all' ? undefined : tab,
    q: dq.search || undefined,
    username: dq.user || undefined,
    action: v.action && v.action !== 'all' ? v.action : undefined,
    table_name: histTable || (v.table && v.table !== 'all' ? v.table : undefined),
    record_id: histId || undefined,
    record: dq.record || undefined,
    details: dq.details || undefined,
    ip: dq.ip || undefined,
    since_hours: sinceHours,
    start,
    end,
  }

  const { data: facets } = useQuery<AuditFacets>({
    queryKey: ['audit-facets', sinceHours, start, end],
    queryFn: async () => (await api.get('/audit/facets', {
      params: { since_hours: sinceHours, start, end },
    })).data,
    placeholderData: keepPreviousData,
  })
  useEffect(() => setFacetsForDefs(facets), [facets])

  const { data, isFetching, isError, error } = useQuery<AuditList>({
    queryKey: ['audit', params],
    queryFn: async () => (await api.get('/audit', { params })).data,
    placeholderData: keepPreviousData,
  })
  const rows = data?.items ?? []
  // Açık detay: listede varsa oradan, yoksa (filtre dışı / 1000 sınırı ötesi) tek kayıt ucu
  const selectedInRows = selectedId !== null ? rows.find((r) => r.id === selectedId) : undefined
  const { data: selectedFetched } = useQuery<AuditEntry>({
    queryKey: ['audit-entry', selectedId],
    queryFn: async () => (await api.get(`/audit/${selectedId}`)).data,
    enabled: selectedId !== null && !selectedInRows && !isFetching,
  })
  const selected = selectedId === null ? null : (selectedInRows ?? selectedFetched ?? null)
  const histLabel = histTable
    ? (rows.find((r) => r.table_name === histTable && r.record_id === histId)?.record_label || `#${histId}`)
    : ''
  const history = histTable ? { table: histTable, label: histLabel } : null
  const paramsKey = JSON.stringify(params)
  useEffect(() => setPage(0), [paramsKey])
  const pageRows = rows.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage)

  const facetCounts = useMemo(() => {
    if (!facets) return undefined
    const toMap = (xs: { value: string; count: number }[]) =>
      ({ all: facets.total, ...Object.fromEntries(xs.map((x) => [x.value, x.count])) })
    return { action: toMap(facets.actions), table: toMap(facets.tables), time: {} }
  }, [facets])

  const exportCsv = useMutation({
    mutationFn: async () => {
      const res = await api.get('/audit/export', { params, responseType: 'blob' })
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url
      const stamp = (v?: string) => (v ?? '').replace(/[-:]/g, '').replace('T', '-')
      a.download = sinceHours ? `audit_son${sinceHours}saat.csv`
        : start ? `audit_${stamp(start)}_${end ? stamp(end) : 'simdi'}.csv` : 'audit_son1000.csv'
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  // ---- Aktif filtre çipleri ----
  const chips: { key: string; label: string; onDelete: () => void }[] = []
  if (history) chips.push({ key: 'history', label: `Kayıt geçmişi: ${meta?.tables[history.table] ?? history.table} · ${history.label}`, onDelete: () => patchUrl({ audit_hist_t: null, audit_hist_id: null }) })
  if (search) chips.push({ key: 'q', label: `Arama: ${search}`, onDelete: () => setSearch('') })
  for (const d of defs) {
    if (!cf.active(d.key)) continue
    let shown = v[d.key]
    if (d.kind === 'status') shown = d.options?.find((o) => o.value === v[d.key])?.label ?? v[d.key]
    if (d.key === 'time' && preset === 'custom') {
      shown = dateFrom ? `${formatLocalInput(dateFrom)} → ${dateTo ? formatLocalInput(dateTo) : 'şimdi'}`
        : 'Özel aralık (tarih seçin)'
    }
    chips.push({ key: d.key, label: `${d.label}: ${shown}`, onDelete: () => cf.set(d.key, d.kind === 'status' ? 'all' : '') })
  }
  // TEK URL güncellemesi: ayrı ayrı set'ler aynı anda çalışınca birbirini ezer
  const clearAll = () => patchUrl({
    ...Object.fromEntries(defs.map((d) => [`audit_f_${d.key}`, null])),
    audit_q: null, audit_hist_t: null, audit_hist_id: null, audit_from: null, audit_to: null,
  })

  const showHistory = (e: AuditEntry) => patchUrl({
    audit_hist_t: e.table_name, audit_hist_id: e.record_id ?? null, audit_tab: null, audit_entry: null,
  })

  const colW = { time: 150, user: 160, action: 180, table: 140, record: 210, ip: 120 }

  return (
    <Stack spacing={1.5}>
      {/* Kategori sekmeleri */}
      <Tabs value={tab} onChange={(_, t) => setTab(t)} variant="scrollable" allowScrollButtonsMobile
            sx={{ minHeight: 36, borderBottom: '1px solid', borderColor: 'divider' }}>
        {(['all', ...CATEGORY_TABS] as Tab_[]).map((t) => (
          <Tab key={t} value={t} sx={{ minHeight: 36, py: 0.5, textTransform: 'none' }}
               label={
                 <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                   {t === 'all' ? 'Tümü' : (meta?.categories[t] ?? t)}
                   <Box component="span" sx={{ px: 0.75, borderRadius: 1, fontSize: 11, lineHeight: '18px',
                                               bgcolor: 'action.selected', fontVariantNumeric: 'tabular-nums' }}>
                     {facets ? (t === 'all' ? facets.total : facets.categories[t]) : '·'}
                   </Box>
                 </Box>
               } />
        ))}
      </Tabs>

      {/* Araç çubuğu */}
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} sx={{ alignItems: { md: 'center' } }}>
        <TextField size="small" placeholder="Kayıtlarda ara (ad, detay, kullanıcı)…" value={search}
                   onChange={(e) => setSearch(e.target.value)} sx={{ minWidth: 300 }}
                   slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }} />
        <TimeRangePicker preset={preset} from={dateFrom} to={dateTo} onChange={changeTime} />
        <Box sx={{ flexGrow: 1 }} />
        <Tooltip title="Yenile">
          <IconButton onClick={() => { queryClient.invalidateQueries({ queryKey: ['audit'] }); queryClient.invalidateQueries({ queryKey: ['audit-facets'] }) }}>
            <RefreshIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Button variant="outlined" startIcon={<FileDownloadIcon />}
                onClick={() => exportCsv.mutate()} disabled={exportCsv.isPending}>
          Dışa Aktar (CSV)
        </Button>
      </Stack>

      {/* Aktif filtreler */}
      {chips.length > 0 && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 0.75 }}>
          {chips.map((c) => (
            <Chip key={c.key} size="small" color="primary" variant="outlined" label={c.label} onDelete={c.onDelete}
                  icon={c.key === 'history' ? <HistoryIcon /> : undefined} />
          ))}
          <Button size="small" onClick={clearAll}>Tümünü temizle</Button>
        </Box>
      )}

      {data?.capped && (
        <Alert severity="info" variant="outlined" sx={{ py: 0 }}>
          Filtreye uyan kayıtların <b>en yeni {data.limit}</b> tanesi gösteriliyor. Daha eskisi için zaman
          aralığını daraltın ya da <b>CSV</b> alın — CSV seçili aralığın tamamını içerir.
        </Alert>
      )}
      {isError && <Alert severity="error">{apiErrorMessage(error)}</Alert>}

      <Box sx={{ position: 'relative', border: '1px solid', borderColor: 'divider', borderRadius: 1.5, overflowX: 'auto' }}>
        {isFetching && <LinearProgress sx={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2 }} />}
        <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 1100 }}>
          <colgroup>
            <col style={{ width: colW.time }} />
            <col style={{ width: colW.user }} />
            <col style={{ width: colW.action }} />
            <col style={{ width: colW.table }} />
            <col style={{ width: colW.record }} />
            <col />
            <col style={{ width: colW.ip }} />
          </colgroup>
          <TableHead>
            <TableRow>
              {defs.map((d) => <ColHeaderCell key={d.key} def={d} cf={cf} />)}
            </TableRow>
          </TableHead>
          <TableBody>
            {pageRows.map((e) => (
              <TableRow key={e.id} hover onClick={() => setSelectedId(e.id)} selected={e.id === selectedId}
                        sx={{ cursor: 'pointer', verticalAlign: 'top',
                              ...(e.action === 'login_failed' && {
                                bgcolor: (t) => alpha(t.palette.error.main, 0.06),
                              }) }}>
                <TableCell>
                  <Tooltip title={relativeTime(e.created_at)} placement="top-start">
                    <Typography variant="body2" sx={{ fontVariantNumeric: 'tabular-nums' }} noWrap>
                      {formatAuditTime(e.created_at)}
                    </Typography>
                  </Tooltip>
                </TableCell>
                <TableCell><UserCell username={e.username} fullName={e.user_full_name} /></TableCell>
                <TableCell><ActionDot action={e.action} meta={meta} withLabel /></TableCell>
                <TableCell>
                  <Typography variant="body2" color="text.secondary" noWrap>
                    {meta?.tables[e.table_name] ?? e.table_name}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Tooltip title={e.record_label || ''} placement="top-start" disableHoverListener={!e.record_label}>
                    <Typography variant="body2" noWrap sx={{ fontWeight: 500 }}>
                      {e.record_label || (e.record_id ? `#${e.record_id}` : '—')}
                    </Typography>
                  </Tooltip>
                </TableCell>
                <TableCell>
                  <Typography variant="body2" sx={{
                    display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
                    wordBreak: 'break-word', color: e.summary ? 'text.primary' : 'text.disabled',
                  }}>
                    {e.summary || '—'}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="body2" noWrap sx={{ fontFamily: MONO_FONT, fontSize: 11.5, lineHeight: '20px', color: 'text.secondary' }}>
                    {e.ip_address || '—'}
                  </Typography>
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && !isFetching && (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 5, color: 'text.secondary' }}>
                  Bu filtrelerle kayıt bulunamadı.
                  {chips.length > 0 && <Button size="small" onClick={clearAll} sx={{ ml: 1 }}>Filtreleri temizle</Button>}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Box>
      <TablePagination
        component="div"
        count={rows.length}
        page={page}
        onPageChange={(_e, p) => setPage(p)}
        rowsPerPage={rowsPerPage}
        onRowsPerPageChange={(e) => { setRowsPerPage(parseInt(e.target.value, 10)); setPage(0) }}
        rowsPerPageOptions={[25, 50, 100]}
        labelRowsPerPage="Sayfa başına satır"
        labelDisplayedRows={({ from: f, to: t, count }) => `${f}–${t} / ${count}${data?.capped ? '+' : ''}`}
      />

      <ColumnFilterMenu cf={cf} facetCounts={facetCounts} />
      <AuditDetailDrawer entry={selected} meta={meta} onClose={() => setSelectedId(null)}
                         onShowHistory={showHistory}
                         onOpenRecord={(e) => { setOpenRecord({ table: e.table_name, id: Number(e.record_id) }) }} />
      <CertificateDetailDrawer
        certId={openRecord && (openRecord.table === 'certificates' || openRecord.table === 'SSLCertificates') ? openRecord.id : null}
        onClose={() => setOpenRecord(null)} />
      <DomainDetailDrawer domainId={openRecord?.table === 'domains' ? openRecord.id : null}
                          onClose={() => setOpenRecord(null)} />
      <ApplicationDetailDrawer appId={openRecord?.table === 'applications' ? openRecord.id : null}
                               onClose={() => setOpenRecord(null)} />
    </Stack>
  )
}
