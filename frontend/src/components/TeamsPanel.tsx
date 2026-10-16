import AddIcon from '@mui/icons-material/Add'
import FileDownloadIcon from '@mui/icons-material/FileDownload'
import RefreshIcon from '@mui/icons-material/Refresh'
import SearchIcon from '@mui/icons-material/Search'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import {
  Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, InputAdornment,
  LinearProgress, MenuItem, Stack, Tab, Table, TableBody, TableCell, TableHead, TablePagination, TableRow,
  Tabs, TextField, Tooltip, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useMemo, useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { Team } from '../api/types'
import { useUrlId, useUrlPatch, useUrlState } from '../hooks/useUrlState'
import { exportSheet } from '../utils/exportSheet'
import { includesTr, TEAM_TYPE_COLOR, TEAM_TYPE_LABEL } from '../utils/peopleLabels'
import { ColHeaderCell, ColumnFilterMenu, useColumnFilters, type ColDef } from './ColumnFilters'
import { CountLabel } from './PeopleShared'
import TeamDetailDrawer from './TeamDetailDrawer'

/**
 * Ekipler — Kullanıcılar ile aynı kalıp: tip sekmeleri (sayaçlı), arama, kolon hunileri, dikkat
 * çipleri (bildirim e-postası olmayan SY ekipleri), Excel, satır → detay çekmecesi (üyeler dâhil).
 */

type TypeTab = 'all' | 'SY' | 'UG' | 'system'
const NOOP = () => null
const HAS_OPTS = [{ value: 'all', label: 'Tümü' }, { value: 'yes', label: 'Var' }, { value: 'no', label: 'Yok' }]

const emails = (t: Team) => (t.email ?? '').split(/[,;]/).map((s) => s.trim()).filter(Boolean)
const isSystem = (t: Team) => t.type === 'ADMIN' || t.type === 'VIEWER'
const inTypeTab = (t: Team, tab: TypeTab) => tab === 'all' || (tab === 'system' ? isSystem(t) : t.type === tab)
const noEmailSy = (t: Team) => t.type === 'SY' && emails(t).length === 0

function has(n: number | undefined, val: string) { return val === 'yes' ? (n ?? 0) > 0 : (n ?? 0) === 0 }

function Count({ n, warn }: { n?: number; warn?: string }) {
  if (!n && warn) {
    return <Tooltip title={warn}><Typography variant="body2" color="warning.main" sx={{ fontWeight: 600 }}>0</Typography></Tooltip>
  }
  return (
    <Typography variant="body2" sx={{ fontVariantNumeric: 'tabular-nums', color: n ? 'text.primary' : 'text.disabled' }}>
      {n ?? 0}
    </Typography>
  )
}

export default function TeamsPanel() {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const patchUrl = useUrlPatch()
  const [tab, setTab] = useUrlState<TypeTab>('teams_tab', 'all', ['all', 'SY', 'UG', 'system'])
  const [search, setSearch] = useUrlState<string>('teams_q', '')
  const [detailId, setDetailId] = useUrlId('teams_detail')
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState({ name: '', type: 'SY', email: '' })

  const { data: teams, isFetching } = useQuery<Team[]>({
    queryKey: ['teams', 'all'],
    queryFn: async () => (await api.get('/teams')).data,
  })

  const defs = useMemo<ColDef<Team>[]>(() => [
    { key: 'name', label: 'Ekip', kind: 'text', get: NOOP },
    { key: 'type', label: 'Tip', kind: 'status', get: NOOP, options: [] },
    { key: 'members', label: 'Üye', kind: 'status', get: NOOP, options: HAS_OPTS, align: 'right' },
    { key: 'domains', label: 'Domain', kind: 'status', get: NOOP, options: HAS_OPTS, align: 'right' },
    { key: 'apps', label: 'Uygulama', kind: 'status', get: NOOP, options: HAS_OPTS, align: 'right' },
    { key: 'email', label: 'Bildirim E-postası', kind: 'status', get: NOOP, options: HAS_OPTS },
  ], [])
  const cf = useColumnFilters(defs, { urlPrefix: 'teams_f_' })
  const v = cf.values

  const searched = useMemo(() => (teams ?? []).filter((t) => includesTr([t.name, t.email], search)), [teams, search])
  const inTab = useMemo(() => searched.filter((t) => inTypeTab(t, tab)), [searched, tab])
  const columnMatch = (t: Team, skip?: string) =>
    (skip === 'name' || includesTr([t.name], v.name ?? ''))
    && (skip === 'members' || v.members === 'all' || has(t.member_count, v.members))
    && (skip === 'domains' || v.domains === 'all' || has(t.domain_count, v.domains))
    && (skip === 'apps' || v.apps === 'all' || has(t.app_count, v.apps))
    && (skip === 'email' || v.email === 'all' || has(emails(t).length, v.email))
  const rows = inTab.filter((t) => columnMatch(t))
  const filterKey = JSON.stringify([tab, search, v])
  useEffect(() => setPage(0), [filterKey])
  const pageRows = rows.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage)

  const facetCounts = useMemo(() => {
    const count = (key: string, n: (t: Team) => number | undefined) => {
      const base = inTab.filter((t) => columnMatch(t, key))
      return { all: base.length, yes: base.filter((t) => has(n(t), 'yes')).length, no: base.filter((t) => has(n(t), 'no')).length }
    }
    return {
      members: count('members', (t) => t.member_count), domains: count('domains', (t) => t.domain_count),
      apps: count('apps', (t) => t.app_count), email: count('email', (t) => emails(t).length),
    }
  }, [inTab, v])  // eslint-disable-line react-hooks/exhaustive-deps

  const tabCount = (t: TypeTab) => searched.filter((x) => inTypeTab(x, t)).length
  const missingEmail = (teams ?? []).filter(noEmailSy).length

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['teams'] })
    queryClient.invalidateQueries({ queryKey: ['team-members'] })
    queryClient.invalidateQueries({ queryKey: ['users'] })
    queryClient.invalidateQueries({ queryKey: ['recent-activity'] })
  }
  const create = useMutation({
    mutationFn: async () => (await api.post('/teams', {
      name: form.name.trim(), type: form.type, email: form.email.trim() || null })).data as Team,
    onSuccess: (t) => {
      enqueueSnackbar('Ekip eklendi', { variant: 'success' })
      invalidate(); setCreateOpen(false); setForm({ name: '', type: 'SY', email: '' })
      setDetailId(t.id)  // üye eklemek için detayı aç
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const onExport = () => exportSheet(
    'ekipler.xlsx', ['Ekip', 'Tip', 'Üye', 'Domain', 'Uygulama', 'Bildirim E-postası'],
    rows.map((t) => [t.name, TEAM_TYPE_LABEL[t.type] ?? t.type, t.member_count ?? 0, t.domain_count ?? 0,
                     t.app_count ?? 0, t.email ?? '']),
  )

  const chips: { key: string; label: string; onDelete: () => void }[] = []
  if (search) chips.push({ key: 'q', label: `Arama: ${search}`, onDelete: () => setSearch('') })
  for (const d of defs) {
    if (!cf.active(d.key)) continue
    const shown = d.kind === 'status' ? (d.options?.find((o) => o.value === v[d.key])?.label ?? v[d.key]) : v[d.key]
    chips.push({ key: d.key, label: `${d.label}: ${shown}`, onDelete: () => cf.set(d.key, d.kind === 'status' ? 'all' : '') })
  }
  const clearAll = () => patchUrl({ ...Object.fromEntries(defs.map((d) => [`teams_f_${d.key}`, null])), teams_q: null })
  const filterable = new Set(['name', 'members', 'domains', 'apps', 'email'])

  return (
    <Stack spacing={1.5}>
      <Tabs value={tab} onChange={(_, t) => setTab(t)} variant="scrollable" allowScrollButtonsMobile
            sx={{ minHeight: 36, borderBottom: '1px solid', borderColor: 'divider' }}>
        {([['all', 'Tümü'], ['SY', 'SY ekipleri'], ['UG', 'UG'], ['system', 'Sistem']] as [TypeTab, string][]).map(([t, l]) => (
          <Tab key={t} value={t} sx={{ minHeight: 36, py: 0.5, textTransform: 'none' }}
               label={<CountLabel label={l} count={teams ? tabCount(t) : undefined} />} />
        ))}
      </Tabs>

      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} sx={{ alignItems: { md: 'center' } }}>
        <TextField size="small" placeholder="Ara (ekip adı, e-posta)…" value={search}
                   onChange={(e) => setSearch(e.target.value)} sx={{ minWidth: 300 }}
                   slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }} />
        {missingEmail > 0 && v.email !== 'no' && (
          <Tooltip title="Bu SY ekiplerinin domainleri için süre uyarısı e-postası gönderilemez">
            <Chip size="small" color="warning" variant="outlined" icon={<WarningAmberIcon />}
                  label={`${missingEmail} SY ekibinin bildirim e-postası yok`}
                  onClick={() => { setTab('SY'); cf.set('email', 'no') }} />
          </Tooltip>
        )}
        <Box sx={{ flexGrow: 1 }} />
        <Tooltip title="Yenile"><IconButton onClick={invalidate}><RefreshIcon fontSize="small" /></IconButton></Tooltip>
        <Button variant="outlined" startIcon={<FileDownloadIcon />} onClick={onExport} disabled={!rows.length}>
          Dışa Aktar (Excel)
        </Button>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>Ekip Ekle</Button>
      </Stack>

      {chips.length > 0 && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 0.75 }}>
          {chips.map((c) => <Chip key={c.key} size="small" color="primary" variant="outlined" label={c.label} onDelete={c.onDelete} />)}
          <Button size="small" onClick={clearAll}>Tümünü temizle</Button>
        </Box>
      )}

      <Box sx={{ position: 'relative', border: '1px solid', borderColor: 'divider', borderRadius: 1.5, overflowX: 'auto' }}>
        {isFetching && <LinearProgress sx={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2 }} />}
        <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 900 }}>
          <colgroup>
            <col style={{ width: 280 }} /><col style={{ width: 190 }} /><col style={{ width: 90 }} />
            <col style={{ width: 100 }} /><col style={{ width: 110 }} /><col />
          </colgroup>
          <TableHead>
            <TableRow>
              {defs.map((d) => filterable.has(d.key)
                ? <ColHeaderCell key={d.key} def={d} cf={cf} />
                : <TableCell key={d.key}>{d.label}</TableCell>)}
            </TableRow>
          </TableHead>
          <TableBody>
            {pageRows.map((t) => {
              const list = emails(t)
              return (
                <TableRow key={t.id} hover selected={t.id === detailId} onClick={() => setDetailId(t.id)} sx={{ cursor: 'pointer' }}>
                  <TableCell><Typography variant="body2" noWrap sx={{ fontWeight: 600 }}>{t.name}</Typography></TableCell>
                  <TableCell>
                    <Chip size="small" color={TEAM_TYPE_COLOR[t.type] ?? 'default'} variant={isSystem(t) ? 'filled' : 'outlined'}
                          label={TEAM_TYPE_LABEL[t.type] ?? t.type} />
                  </TableCell>
                  <TableCell align="right">
                    <Count n={t.member_count} warn={t.type === 'SY' ? 'Üyesi yok — bu ekibin verisini hiçbir editör/izleyici göremez' : undefined} />
                  </TableCell>
                  <TableCell align="right"><Count n={t.domain_count} /></TableCell>
                  <TableCell align="right"><Count n={t.app_count} /></TableCell>
                  <TableCell>
                    {list.length ? (
                      <Tooltip title={list.length > 1 ? list.join(', ') : ''} placement="top-start">
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0 }}>
                          <Typography variant="body2" noWrap>{list[0]}</Typography>
                          {list.length > 1 && <Chip size="small" label={`+${list.length - 1}`} sx={{ height: 18, fontSize: 11 }} />}
                        </Box>
                      </Tooltip>
                    ) : t.type === 'SY' ? (
                      <Tooltip title="Bu ekibin domainleri için süre uyarısı e-postası gönderilemez">
                        <Chip size="small" color="warning" icon={<WarningAmberIcon />} label="E-posta yok" />
                      </Tooltip>
                    ) : <Typography variant="body2" color="text.disabled">—</Typography>}
                  </TableCell>
                </TableRow>
              )
            })}
            {!rows.length && !isFetching && (
              <TableRow>
                <TableCell colSpan={6} align="center" sx={{ py: 5, color: 'text.secondary' }}>
                  {teams?.length ? 'Bu filtrelerle ekip bulunamadı.' : 'Henüz ekip yok.'}
                  {(chips.length > 0 || tab !== 'all') && (
                    <Button size="small" sx={{ ml: 1 }} onClick={() => { clearAll(); setTab('all') }}>Filtreleri temizle</Button>
                  )}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Box>
      <TablePagination
        component="div" count={rows.length} page={page} onPageChange={(_e, p) => setPage(p)}
        rowsPerPage={rowsPerPage} onRowsPerPageChange={(e) => { setRowsPerPage(parseInt(e.target.value, 10)); setPage(0) }}
        rowsPerPageOptions={[10, 25, 50, 100]} labelRowsPerPage="Sayfa başına satır"
        labelDisplayedRows={({ from, to, count }) => `${from}–${to} / ${count}`}
      />

      <ColumnFilterMenu cf={cf} facetCounts={facetCounts} />
      <TeamDetailDrawer team={(teams ?? []).find((t) => t.id === detailId) ?? null}
                        onClose={() => setDetailId(null)} onChanged={invalidate} />

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Ekip Ekle</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Ekip Adı" size="small" value={form.name} autoFocus
                       onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
            <TextField select label="Tip" size="small" value={form.type}
                       onChange={(e) => setForm((f) => ({ ...f, type: e.target.value }))}
                       helperText="Tip sonradan değiştirilemez. Yönetici/İzleyici sistem tekilidir.">
              <MenuItem value="SY">SY ekibi (domain/uygulama sahibi)</MenuItem>
              <MenuItem value="UG">UG (yalnız etiket)</MenuItem>
            </TextField>
            <TextField label="Bildirim E-postası" size="small" type="email" value={form.email}
                       onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                       placeholder="ör. moneytalks@banka.local, noc@banka.local"
                       helperText="SY ekipleri için bildirim kaynağı. Birden çok adresi virgülle ayırın." />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Vazgeç</Button>
          <Button variant="contained" onClick={() => create.mutate()} disabled={!form.name.trim() || create.isPending}>Ekle</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  )
}
