import FileDownloadIcon from '@mui/icons-material/FileDownload'
import RefreshIcon from '@mui/icons-material/Refresh'
import SearchIcon from '@mui/icons-material/Search'
import {
  Alert, Box, Button, Chip, IconButton, InputAdornment, LinearProgress, MenuItem, Stack, Tab, Table,
  TableBody, TableCell, TableHead, TablePagination, TableRow, Tabs, TextField, Tooltip, Typography,
} from '@mui/material'
import { alpha } from '@mui/material/styles'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { MailHistoryEntry, MailHistoryFacets, MailHistoryList, MailStatus, MailType } from '../api/types'
import { useUrlPatch, useUrlState } from '../hooks/useUrlState'
import { daysLeftColor, daysLeftLabel } from '../theme'
import { formatAuditTime, formatLocalInput, presetHours, relativeTime, TIME_PRESETS, type TimePreset } from '../utils/auditFormat'
import { exportSheet } from '../utils/exportSheet'
import { MAIL_STATUS, MAIL_TYPE } from '../utils/mailFormat'
import CertificateDetailDrawer from './CertificateDetailDrawer'
import { ColHeaderCell, ColumnFilterMenu, useColumnFilters, type ColDef } from './ColumnFilters'
import DomainDetailDrawer from './DomainDetailDrawer'
import MailHistoryDetailDrawer from './MailHistoryDetailDrawer'
import TimeRangePicker from './TimeRangePicker'

/**
 * Mail Gönderim Geçmişi — Audit Log ile aynı kalıp: durum sekmeleri (sayaçlı), Grafana tarzı
 * zaman seçici, her kolonda huni filtresi, tüm görünüm durumu URL'de (mail_*). Filtreler
 * SUNUCUDA, limitten önce uygulanır; liste filtreye uyan en yeni 1000 kayıt.
 */

type StatusTab = 'all' | MailStatus
const STATUS_TABS: MailStatus[] = ['sent', 'pending', 'failed']
const NOOP = () => null
const TYPES = Object.keys(MAIL_TYPE) as MailType[]

function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

function recordOf(r: MailHistoryEntry): { label: string; kind: 'cert' | 'domain' | null } {
  if (r.certificate_name) return { label: r.certificate_name, kind: 'cert' }
  if (r.domain_name) return { label: r.domain_name, kind: 'domain' }
  return { label: '—', kind: null }
}

export default function MailHistoryPanel() {
  const queryClient = useQueryClient()
  const patchUrl = useUrlPatch()
  const [tab, setTab] = useUrlState<StatusTab>('mail_status', 'all', ['all', ...STATUS_TABS])
  const [search, setSearch] = useUrlState<string>('mail_q', '')
  const [channel, setChannel] = useUrlState<string>('mail_channel', 'email')  // '' = tüm kanallar
  const [dateFrom] = useUrlState<string>('mail_from', '')
  const [dateTo] = useUrlState<string>('mail_to', '')
  const [detailRaw, setDetailRaw] = useUrlState<string>('mail_detail', '')  // "<kaynak>:<id>"
  const detail = useMemo(() => {
    const m = /^([a-z_]+):(\d+)$/.exec(detailRaw)
    return m ? { source: m[1], id: Number(m[2]) } : null
  }, [detailRaw])
  const [openRecord, setOpenRecord] = useState<{ kind: 'cert' | 'domain'; id: number } | null>(null)
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(50)

  const [facetsForDefs, setFacetsForDefs] = useState<MailHistoryFacets | undefined>()
  const defs = useMemo<ColDef<MailHistoryEntry>[]>(() => [
    { key: 'time', label: 'Zaman', kind: 'status', options: TIME_PRESETS.filter((p) => p.value !== 'custom'), get: NOOP },
    { key: 'type', label: 'Tür', kind: 'status', get: NOOP, options: [
      { value: 'all', label: 'Tümü' },
      ...TYPES.filter((t) => !facetsForDefs || facetsForDefs.types[t] > 0)
        .map((t) => ({ value: t, label: MAIL_TYPE[t].label })),
    ] },
    { key: 'record', label: 'Sertifika / Domain', kind: 'text', get: NOOP },
    { key: 'recipient', label: 'Alıcı', kind: 'text', get: NOOP },
    { key: 'days', label: 'Kalan Gün', kind: 'status', get: NOOP, options: [{ value: 'all', label: 'Tümü' }] },
    { key: 'status', label: 'Durum', kind: 'status', get: NOOP, options: [{ value: 'all', label: 'Tümü' }] },
    { key: 'subject', label: 'Konu / Hata', kind: 'text', get: NOOP },
  ], [facetsForDefs])
  const cf = useColumnFilters(defs, { urlPrefix: 'mail_f_' })
  const v = cf.values
  const preset = (TIME_PRESETS.some((p) => p.value === v.time) ? v.time : 'all') as TimePreset
  useEffect(() => {
    if (preset !== 'custom' && (dateFrom || dateTo)) patchUrl({ mail_from: null, mail_to: null })
  }, [preset])  // eslint-disable-line react-hooks/exhaustive-deps
  const sinceHours = presetHours(preset)
  const start = preset === 'custom' ? dateFrom || undefined : undefined
  const end = preset === 'custom' ? dateTo || undefined : undefined
  const changeTime = (p: TimePreset, f?: string, t?: string) => patchUrl({
    mail_f_time: p === 'all' ? null : p,
    mail_from: p === 'custom' ? (f ?? null) : null,
    mail_to: p === 'custom' ? (t || null) : null,
  })

  const dq = useDebounced({ search, record: v.record, recipient: v.recipient, subject: v.subject })
  const common = {
    channel: channel || undefined,
    mail_type: v.type && v.type !== 'all' ? v.type : undefined,
    q: dq.search || undefined,
    record: dq.record || undefined,
    recipient: dq.recipient || undefined,
    subject: dq.subject || undefined,
    since_hours: sinceHours, start, end,
  }
  const params = { ...common, status: tab === 'all' ? undefined : tab }

  const { data: facets } = useQuery<MailHistoryFacets>({
    queryKey: ['mail-history-facets', common],
    queryFn: async () => (await api.get('/notifications/history/facets', { params: common })).data,
    placeholderData: keepPreviousData,
  })
  useEffect(() => setFacetsForDefs(facets), [facets])
  const { data, isFetching, isError, error } = useQuery<MailHistoryList>({
    queryKey: ['mail-history', params],
    queryFn: async () => (await api.get('/notifications/history', { params })).data,
    placeholderData: keepPreviousData,
  })
  const rows = data?.items ?? []
  const paramsKey = JSON.stringify(params)
  useEffect(() => setPage(0), [paramsKey])
  const pageRows = rows.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage)

  const facetCounts = useMemo(() => facets ? {
    type: { all: facets.total, ...facets.types }, time: {}, days: {}, status: {},
  } : undefined, [facets])

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['mail-history'] })
    queryClient.invalidateQueries({ queryKey: ['mail-history-facets'] })
  }

  // Ekranda görünen = indirilen. .xlsx — çok satırlı konu/hata metni hücrede bozulmaz.
  const onExport = () => exportSheet(
    `mail_gecmisi_${sinceHours ? `son${sinceHours}saat` : start ? `${start}_${end ?? 'simdi'}`.replace(/[:]/g, '') : 'son1000'}.xlsx`,
    ['Tarih', 'Tür', 'Sertifika / Domain', 'Alıcılar', 'Paydaş', 'Konu', 'Kalan Gün', 'Kanal', 'Durum', 'Deneme', 'Hata'],
    rows.map((r) => [
      r.sent_at ? new Date(r.sent_at).toLocaleString('tr-TR') : '', MAIL_TYPE[r.mail_type]?.label ?? r.mail_type,
      recordOf(r).label, r.recipients.join(', '), r.stakeholder ?? '', r.subject ?? '', r.days_left ?? '',
      r.channel, MAIL_STATUS[r.status]?.label ?? r.status, r.attempts ?? '', r.error ?? '',
    ]),
  )

  // Aktif filtre çipleri
  const chips: { key: string; label: string; onDelete: () => void }[] = []
  if (search) chips.push({ key: 'q', label: `Arama: ${search}`, onDelete: () => setSearch('') })
  if (channel !== 'email') chips.push({ key: 'ch', label: `Kanal: ${channel || 'Tümü'}`, onDelete: () => setChannel('email') })
  for (const d of defs) {
    if (!cf.active(d.key)) continue
    let shown = d.kind === 'status' ? (d.options?.find((o) => o.value === v[d.key])?.label ?? v[d.key]) : v[d.key]
    if (d.key === 'time' && preset === 'custom') {
      shown = dateFrom ? `${formatLocalInput(dateFrom)} → ${dateTo ? formatLocalInput(dateTo) : 'şimdi'}` : 'Özel aralık'
    }
    chips.push({ key: d.key, label: `${d.label}: ${shown}`, onDelete: () => cf.set(d.key, d.kind === 'status' ? 'all' : '') })
  }
  const clearAll = () => patchUrl({
    ...Object.fromEntries(defs.map((d) => [`mail_f_${d.key}`, null])),
    mail_q: null, mail_channel: null, mail_from: null, mail_to: null,
  })

  // Yalnız gerçekten filtrelenebilen kolonlarda huni göster (durum sekmede, kalan gün bilgi amaçlı)
  const filterable = new Set(['time', 'type', 'record', 'recipient', 'subject'])

  return (
    <Stack spacing={1.5}>
      {/* Durum sekmeleri */}
      <Tabs value={tab} onChange={(_, t) => setTab(t)} variant="scrollable" allowScrollButtonsMobile
            sx={{ minHeight: 36, borderBottom: '1px solid', borderColor: 'divider' }}>
        {(['all', ...STATUS_TABS] as StatusTab[]).map((t) => {
          const count = facets ? (t === 'all' ? facets.total : facets.statuses[t]) : undefined
          const alarm = t === 'failed' && !!count
          return (
            <Tab key={t} value={t} sx={{ minHeight: 36, py: 0.5, textTransform: 'none' }} label={
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                {t === 'all' ? 'Tümü' : MAIL_STATUS[t].label}
                <Box component="span" sx={{ px: 0.75, borderRadius: 1, fontSize: 11, lineHeight: '18px',
                                            fontVariantNumeric: 'tabular-nums',
                                            bgcolor: alarm ? 'error.main' : 'action.selected',
                                            color: alarm ? 'error.contrastText' : 'inherit' }}>
                  {count ?? '·'}
                </Box>
              </Box>
            } />
          )
        })}
      </Tabs>

      {/* Araç çubuğu */}
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} sx={{ alignItems: { md: 'center' } }}>
        <TextField size="small" placeholder="Ara (alıcı, konu, sertifika, domain)…" value={search}
                   onChange={(e) => setSearch(e.target.value)} sx={{ minWidth: 300 }}
                   slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }} />
        <TimeRangePicker preset={preset} from={dateFrom} to={dateTo} onChange={changeTime} />
        <TextField select size="small" label="Kanal" value={channel}
                   onChange={(e) => setChannel(e.target.value)} sx={{ width: 140 }}>
          <MenuItem value="email">E-posta</MenuItem>
          <MenuItem value="">Tümü</MenuItem>
        </TextField>
        <Box sx={{ flexGrow: 1 }} />
        <Tooltip title="Yenile"><IconButton onClick={refresh}><RefreshIcon fontSize="small" /></IconButton></Tooltip>
        <Button variant="outlined" startIcon={<FileDownloadIcon />} onClick={onExport} disabled={!rows.length}>
          Dışa Aktar (Excel)
        </Button>
      </Stack>

      {chips.length > 0 && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 0.75 }}>
          {chips.map((c) => <Chip key={c.key} size="small" color="primary" variant="outlined" label={c.label} onDelete={c.onDelete} />)}
          <Button size="small" onClick={clearAll}>Tümünü temizle</Button>
        </Box>
      )}
      {data?.capped && (
        <Alert severity="info" variant="outlined" sx={{ py: 0 }}>
          Filtreye uyan kayıtların <b>en yeni {data.limit}</b> tanesi gösteriliyor. Daha eskisi için zaman aralığını daraltın.
        </Alert>
      )}
      {isError && <Alert severity="error">{apiErrorMessage(error)}</Alert>}

      <Box sx={{ position: 'relative', border: '1px solid', borderColor: 'divider', borderRadius: 1.5, overflowX: 'auto' }}>
        {isFetching && <LinearProgress sx={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2 }} />}
        <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 1150 }}>
          <colgroup>
            <col style={{ width: 150 }} /><col style={{ width: 170 }} /><col style={{ width: 210 }} />
            <col style={{ width: 230 }} /><col style={{ width: 110 }} /><col style={{ width: 120 }} /><col />
          </colgroup>
          <TableHead>
            <TableRow>
              {defs.map((d) => filterable.has(d.key)
                ? <ColHeaderCell key={d.key} def={d} cf={cf} />
                : <TableCell key={d.key}>{d.label}</TableCell>)}
            </TableRow>
          </TableHead>
          <TableBody>
            {pageRows.map((r) => {
              const rec = recordOf(r)
              const key = `${r.source}:${r.id}`
              return (
                <TableRow key={key} hover selected={detailRaw === key} onClick={() => setDetailRaw(key)}
                          sx={{ cursor: 'pointer', verticalAlign: 'top',
                                ...(r.status === 'failed' && { bgcolor: (t) => alpha(t.palette.error.main, 0.06) }) }}>
                  <TableCell>
                    <Tooltip title={r.sent_at ? relativeTime(r.sent_at) : ''} placement="top-start">
                      <Typography variant="body2" noWrap sx={{ fontVariantNumeric: 'tabular-nums' }}>
                        {r.sent_at ? formatAuditTime(r.sent_at) : '—'}
                      </Typography>
                    </Tooltip>
                  </TableCell>
                  <TableCell>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0 }}>
                      <Box component="span" sx={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
                                                  bgcolor: MAIL_TYPE[r.mail_type]?.color ?? 'text.disabled' }} />
                      <Typography variant="body2" noWrap sx={{ fontWeight: 500 }}>
                        {MAIL_TYPE[r.mail_type]?.label ?? r.mail_type}
                      </Typography>
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" noWrap sx={{ fontWeight: 500 }}>{rec.label}</Typography>
                    {rec.kind === 'domain' && <Typography variant="caption" color="text.secondary">domain</Typography>}
                  </TableCell>
                  <TableCell>
                    <Tooltip title={r.recipients.length > 1 ? r.recipients.join(', ') : ''} placement="top-start">
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0 }}>
                        <Typography variant="body2" noWrap>{r.recipients[0] ?? r.recipient ?? '—'}</Typography>
                        {r.recipients.length > 1 && (
                          <Chip size="small" label={`+${r.recipients.length - 1}`} sx={{ height: 18, fontSize: 11 }} />
                        )}
                      </Box>
                    </Tooltip>
                    {r.stakeholder && (
                      <Typography variant="caption" color="text.secondary" noWrap component="div">{r.stakeholder}</Typography>
                    )}
                  </TableCell>
                  <TableCell>
                    {r.days_left === null || r.days_left === undefined ? '—'
                      : <Tooltip title={daysLeftLabel(r.days_left)}>
                          <Chip size="small" color={daysLeftColor(r.days_left)}
                                label={r.days_left < 0 ? `${-r.days_left}g geçti` : `${r.days_left}g kaldı`} />
                        </Tooltip>}
                  </TableCell>
                  <TableCell>
                    <Chip size="small" variant={r.status === 'sent' ? 'outlined' : 'filled'}
                          color={MAIL_STATUS[r.status]?.color ?? 'default'} label={MAIL_STATUS[r.status]?.label ?? r.status} />
                    {r.status !== 'sent' && !!r.attempts && (
                      <Typography variant="caption" color="text.secondary" component="div">{r.attempts} deneme</Typography>
                    )}
                  </TableCell>
                  <TableCell>
                    {r.error ? (
                      <Typography variant="body2" color="error.main" sx={{ display: '-webkit-box', WebkitLineClamp: 2,
                                  WebkitBoxOrient: 'vertical', overflow: 'hidden', wordBreak: 'break-word' }}>
                        {r.error}
                      </Typography>
                    ) : (
                      <Typography variant="body2" color="text.secondary" noWrap>{r.subject ?? '—'}</Typography>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
            {!rows.length && !isFetching && (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 5, color: 'text.secondary' }}>
                  Bu filtrelerle mail kaydı bulunamadı.
                  {chips.length > 0 && <Button size="small" onClick={clearAll} sx={{ ml: 1 }}>Filtreleri temizle</Button>}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Box>
      <TablePagination
        component="div" count={rows.length} page={page} onPageChange={(_e, p) => setPage(p)}
        rowsPerPage={rowsPerPage} onRowsPerPageChange={(e) => { setRowsPerPage(parseInt(e.target.value, 10)); setPage(0) }}
        rowsPerPageOptions={[25, 50, 100]} labelRowsPerPage="Sayfa başına satır"
        labelDisplayedRows={({ from, to, count }) => `${from}–${to} / ${count}${data?.capped ? '+' : ''}`}
      />

      <ColumnFilterMenu cf={cf} facetCounts={facetCounts} />
      <MailHistoryDetailDrawer item={detail} onClose={() => setDetailRaw('')} onChanged={refresh}
                               onOpenRecord={(kind, id) => setOpenRecord({ kind, id })} />
      <CertificateDetailDrawer certId={openRecord?.kind === 'cert' ? openRecord.id : null} onClose={() => setOpenRecord(null)} />
      <DomainDetailDrawer domainId={openRecord?.kind === 'domain' ? openRecord.id : null} onClose={() => setOpenRecord(null)} />
    </Stack>
  )
}
