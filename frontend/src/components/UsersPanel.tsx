import AddIcon from '@mui/icons-material/Add'
import FileDownloadIcon from '@mui/icons-material/FileDownload'
import RefreshIcon from '@mui/icons-material/Refresh'
import SearchIcon from '@mui/icons-material/Search'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, InputAdornment,
  LinearProgress, MenuItem, Stack, Switch, Tab, Table, TableBody, TableCell, TableHead, TablePagination,
  TableRow, Tabs, TextField, Tooltip, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useMemo, useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { AppUser, Team } from '../api/types'
import { useUrlId, useUrlPatch, useUrlState } from '../hooks/useUrlState'
import { formatAuditTime, relativeTime } from '../utils/auditFormat'
import { exportSheet } from '../utils/exportSheet'
import {
  includesTr, inLoginBucket, LOGIN_BUCKETS, missingScope, ROLE_CHIP, ROLE_OPTIONS, type LoginBucket,
} from '../utils/peopleLabels'
import { ColHeaderCell, ColumnFilterMenu, useColumnFilters, type ColDef } from './ColumnFilters'
import { CountLabel, PersonAvatar } from './PeopleShared'
import UserDetailDrawer from './UserDetailDrawer'

/**
 * Kullanıcılar — Audit Log / Mail Geçmişi kalıbı: rol sekmeleri (sayaçlı), arama, her kolonda huni
 * filtresi, aktif filtre çipleri, Excel dışa aktarma, satıra tıklayınca detay çekmecesi. Tüm görünüm
 * durumu URL'de (users_*). Liste küçük olduğundan süzme istemcide.
 */

type RoleTab = 'all' | 'admin' | 'editor' | 'viewer' | 'allviewer' | 'none'
const ROLE_TABS: RoleTab[] = ['admin', 'editor', 'viewer', 'allviewer', 'none']
const NOOP = () => null
const EMPTY_FORM = { username: '', password: '', email: '', full_name: '', auth_source: 'local', role: 'none' }

function teamsMatch(u: AppUser, v: string): boolean {
  if (v === '__none') return !(u.team_ids?.length)
  if (v === '__noscope') return missingScope(u)
  if (v.startsWith('t:')) return (u.team_ids ?? []).includes(Number(v.slice(2)))
  return true
}

export default function UsersPanel() {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const patchUrl = useUrlPatch()
  const [tab, setTab] = useUrlState<RoleTab>('users_tab', 'all', ['all', ...ROLE_TABS])
  const [search, setSearch] = useUrlState<string>('users_q', '')
  const [detailId, setDetailId] = useUrlId('users_detail')
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)

  const { data: users, isFetching } = useQuery<AppUser[]>({
    queryKey: ['users'],
    queryFn: async () => (await api.get('/users')).data,
  })
  const { data: teams } = useQuery<Team[]>({
    queryKey: ['teams', 'all'],
    queryFn: async () => (await api.get('/teams')).data,
  })

  const defs = useMemo<ColDef<AppUser>[]>(() => [
    { key: 'user', label: 'Kullanıcı', kind: 'text', get: NOOP },
    { key: 'email', label: 'E-posta', kind: 'text', get: NOOP },
    { key: 'source', label: 'Kaynak', kind: 'status', get: NOOP, options: [
      { value: 'all', label: 'Tümü' }, { value: 'ldap', label: 'LDAP' }, { value: 'local', label: 'Lokal' }] },
    { key: 'role', label: 'Rol', kind: 'status', get: NOOP, options: [] },
    { key: 'teams', label: 'Takımlar (kapsam)', kind: 'status', get: NOOP, options: [
      { value: 'all', label: 'Tümü' },
      { value: '__noscope', label: 'Kapsam eksik (SY ekibi yok)' },
      { value: '__none', label: 'Hiçbir takımda değil' },
      ...(teams ?? []).map((t) => ({ value: `t:${t.id}`, label: t.name })),
    ] },
    { key: 'active', label: 'Durum', kind: 'status', get: NOOP, options: [
      { value: 'all', label: 'Tümü' }, { value: 'active', label: 'Aktif' }, { value: 'inactive', label: 'Pasif' }] },
    { key: 'login', label: 'Son Giriş', kind: 'status', get: NOOP, options: [
      { value: 'all', label: 'Tümü' }, ...LOGIN_BUCKETS] },
  ], [teams])
  const cf = useColumnFilters(defs, { urlPrefix: 'users_f_' })
  const v = cf.values

  // Sekme + arama → temel küme (sekme sayaçları ve huni sayaçları buradan)
  const searched = useMemo(() => (users ?? []).filter((u) =>
    includesTr([u.username, u.full_name, u.email, ...(u.team_names ?? [])], search)), [users, search])
  const inTab = useMemo(() => tab === 'all' ? searched : searched.filter((u) => u.role === tab), [searched, tab])
  const columnMatch = (u: AppUser, skip?: string) =>
    (skip === 'user' || includesTr([u.username, u.full_name], v.user ?? ''))
    && (skip === 'email' || includesTr([u.email], v.email ?? ''))
    && (skip === 'source' || v.source === 'all' || u.auth_source === v.source)
    && (skip === 'teams' || v.teams === 'all' || teamsMatch(u, v.teams))
    && (skip === 'active' || v.active === 'all' || (v.active === 'active') === u.is_active)
    && (skip === 'login' || v.login === 'all' || inLoginBucket(u.last_login, v.login as LoginBucket))
  const rows = inTab.filter((u) => columnMatch(u))
  const filterKey = JSON.stringify([tab, search, v])
  useEffect(() => setPage(0), [filterKey])
  const pageRows = rows.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage)

  // Huni sayaçları: o kolon HARİÇ diğer filtreler uygulanmış küme üzerinde (Grafana davranışı)
  const facetCounts = useMemo(() => {
    const count = (key: string, pred: (u: AppUser, val: string) => boolean) => {
      const base = inTab.filter((u) => columnMatch(u, key))
      const opts = defs.find((d) => d.key === key)?.options ?? []
      return Object.fromEntries(opts.map((o) => [o.value, o.value === 'all' ? base.length
        : base.filter((u) => pred(u, o.value)).length]))
    }
    return {
      source: count('source', (u, val) => u.auth_source === val),
      teams: count('teams', teamsMatch),
      active: count('active', (u, val) => (val === 'active') === u.is_active),
      login: count('login', (u, val) => inLoginBucket(u.last_login, val as LoginBucket)),
    }
  }, [inTab, v, defs])  // eslint-disable-line react-hooks/exhaustive-deps

  const tabCount = (t: RoleTab) => t === 'all' ? searched.length : searched.filter((u) => u.role === t).length
  const noScope = (users ?? []).filter(missingScope).length

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['users'] })
    queryClient.invalidateQueries({ queryKey: ['teams'] })
    queryClient.invalidateQueries({ queryKey: ['team-members'] })
    queryClient.invalidateQueries({ queryKey: ['recent-activity'] })
  }
  const update = useMutation({
    mutationFn: async ({ id, body }: { id: number; body: Record<string, unknown> }) => api.put(`/users/${id}`, body),
    onSuccess: invalidate,
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const create = useMutation({
    mutationFn: async () => (await api.post('/users', { ...form, password: form.password || null })).data as AppUser,
    onSuccess: (u) => {
      enqueueSnackbar('Kullanıcı eklendi', { variant: 'success' })
      invalidate()
      setCreateOpen(false)
      setForm(EMPTY_FORM)
      setDetailId(u.id)  // ekledikten sonra takım ataması için detayı aç
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const onExport = () => exportSheet(
    'kullanicilar.xlsx',
    ['Kullanıcı', 'Ad Soyad', 'E-posta', 'Kaynak', 'Rol', 'Takımlar', 'Durum', 'Son Giriş', 'Oluşturulma'],
    rows.map((u) => [
      u.username, u.full_name ?? '', u.email ?? '', u.auth_source.toUpperCase(),
      ROLE_CHIP[u.role]?.label ?? u.role, (u.team_names ?? []).join(', '), u.is_active ? 'Aktif' : 'Pasif',
      u.last_login ? formatAuditTime(u.last_login) : 'Hiç', u.created_at ? formatAuditTime(u.created_at) : '',
    ]),
  )

  const chips: { key: string; label: string; onDelete: () => void }[] = []
  if (search) chips.push({ key: 'q', label: `Arama: ${search}`, onDelete: () => setSearch('') })
  for (const d of defs) {
    if (!cf.active(d.key)) continue
    const shown = d.kind === 'status' ? (d.options?.find((o) => o.value === v[d.key])?.label ?? v[d.key]) : v[d.key]
    chips.push({ key: d.key, label: `${d.label}: ${shown}`, onDelete: () => cf.set(d.key, d.kind === 'status' ? 'all' : '') })
  }
  const clearAll = () => patchUrl({
    ...Object.fromEntries(defs.map((d) => [`users_f_${d.key}`, null])), users_q: null,
  })
  const filterable = new Set(['user', 'email', 'source', 'teams', 'active', 'login'])
  const stop = (e: React.SyntheticEvent) => e.stopPropagation()

  return (
    <Stack spacing={1.5}>
      <Tabs value={tab} onChange={(_, t) => setTab(t)} variant="scrollable" allowScrollButtonsMobile
            sx={{ minHeight: 36, borderBottom: '1px solid', borderColor: 'divider' }}>
        {(['all', ...ROLE_TABS] as RoleTab[]).map((t) => (
          <Tab key={t} value={t} sx={{ minHeight: 36, py: 0.5, textTransform: 'none' }}
               label={<CountLabel label={t === 'all' ? 'Tümü' : ROLE_CHIP[t].label} count={users ? tabCount(t) : undefined}
                                  alarm={t === 'none'} />} />
        ))}
      </Tabs>

      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} sx={{ alignItems: { md: 'center' } }}>
        <TextField size="small" placeholder="Ara (ad, kullanıcı, e-posta, takım)…" value={search}
                   onChange={(e) => setSearch(e.target.value)} sx={{ minWidth: 340 }}
                   slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }} />
        {noScope > 0 && v.teams !== '__noscope' && (
          <Tooltip title="Ekip Editörü/İzleyici rolünde ama hiçbir SY ekibinde değil — hiçbir veriyi göremez">
            <Chip size="small" color="warning" variant="outlined" icon={<WarningAmberIcon />}
                  label={`${noScope} kullanıcının kapsamı eksik`} onClick={() => cf.set('teams', '__noscope')} />
          </Tooltip>
        )}
        <Box sx={{ flexGrow: 1 }} />
        <Tooltip title="Yenile"><IconButton onClick={invalidate}><RefreshIcon fontSize="small" /></IconButton></Tooltip>
        <Button variant="outlined" startIcon={<FileDownloadIcon />} onClick={onExport} disabled={!rows.length}>
          Dışa Aktar (Excel)
        </Button>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>Kullanıcı Ekle</Button>
      </Stack>

      {chips.length > 0 && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 0.75 }}>
          {chips.map((c) => <Chip key={c.key} size="small" color="primary" variant="outlined" label={c.label} onDelete={c.onDelete} />)}
          <Button size="small" onClick={clearAll}>Tümünü temizle</Button>
        </Box>
      )}

      <Box sx={{ position: 'relative', border: '1px solid', borderColor: 'divider', borderRadius: 1.5, overflowX: 'auto' }}>
        {isFetching && <LinearProgress sx={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2 }} />}
        <Table size="small" sx={{ tableLayout: 'fixed', minWidth: 1100 }}>
          <colgroup>
            <col style={{ width: 230 }} /><col style={{ width: 210 }} /><col style={{ width: 90 }} />
            <col style={{ width: 170 }} /><col /><col style={{ width: 80 }} /><col style={{ width: 150 }} />
          </colgroup>
          <TableHead>
            <TableRow>
              {defs.map((d) => filterable.has(d.key)
                ? <ColHeaderCell key={d.key} def={d} cf={cf} />
                : <TableCell key={d.key}>{d.label}</TableCell>)}
            </TableRow>
          </TableHead>
          <TableBody>
            {pageRows.map((u) => (
              <TableRow key={u.id} hover selected={u.id === detailId} onClick={() => setDetailId(u.id)}
                        sx={{ cursor: 'pointer', ...(!u.is_active && { '& td': { color: 'text.disabled' } }) }}>
                <TableCell>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, minWidth: 0 }}>
                    <PersonAvatar fullName={u.full_name} username={u.username} muted={!u.is_active} />
                    <Box sx={{ minWidth: 0 }}>
                      <Typography variant="body2" noWrap sx={{ fontWeight: 600 }}>{u.full_name || u.username}</Typography>
                      <Typography variant="caption" color="text.secondary" noWrap component="div">
                        {u.full_name ? u.username : 'Ad Soyad yok'}
                      </Typography>
                    </Box>
                  </Box>
                </TableCell>
                <TableCell><Typography variant="body2" noWrap title={u.email ?? ''}>{u.email ?? '—'}</Typography></TableCell>
                <TableCell><Chip size="small" variant="outlined" label={u.auth_source === 'ldap' ? 'LDAP' : 'Lokal'} /></TableCell>
                <TableCell onClick={stop}>
                  <TextField select size="small" variant="standard" value={u.role} fullWidth
                             onChange={(e) => update.mutate({ id: u.id, body: { role: e.target.value } })}
                             slotProps={{ input: { disableUnderline: true } }}>
                    {ROLE_OPTIONS.map((o) => (
                      <MenuItem key={o.value} value={o.value}>
                        <Chip size="small" color={ROLE_CHIP[o.value]?.color ?? 'default'} label={o.label}
                              sx={{ pointerEvents: 'none' }} />
                      </MenuItem>
                    ))}
                  </TextField>
                </TableCell>
                <TableCell>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0, overflow: 'hidden' }}>
                    {missingScope(u) && (
                      <Tooltip title="Ekip Editörü/İzleyici rolü SY ekibi olmadan hiçbir veriyi göremez">
                        <Chip size="small" color="warning" icon={<WarningAmberIcon />} label="Kapsam yok" />
                      </Tooltip>
                    )}
                    {!missingScope(u) && (u.team_names ?? []).slice(0, 1).map((n) => (
                      <Chip key={n} size="small" variant="outlined" label={n} sx={{ minWidth: 0, maxWidth: '100%' }} />
                    ))}
                    {(u.team_names?.length ?? 0) > (missingScope(u) ? 0 : 1) && (
                      <Tooltip title={(u.team_names ?? []).join(', ')}>
                        <Chip size="small" label={`+${(u.team_names?.length ?? 0) - (missingScope(u) ? 0 : 1)}`} sx={{ flexShrink: 0 }} />
                      </Tooltip>
                    )}
                    {!u.team_names?.length && !missingScope(u) && <Typography variant="body2" color="text.disabled">—</Typography>}
                  </Box>
                </TableCell>
                <TableCell onClick={stop}>
                  <Tooltip title={u.is_active ? 'Aktif — pasife almak için tıklayın' : 'Pasif — giriş yapamaz'}>
                    <Switch size="small" checked={u.is_active}
                            onChange={(e) => update.mutate({ id: u.id, body: { is_active: e.target.checked } })} />
                  </Tooltip>
                </TableCell>
                <TableCell>
                  {u.last_login ? (
                    <Tooltip title={relativeTime(u.last_login)} placement="top-start">
                      <Box>
                        <Typography variant="body2" noWrap sx={{ fontVariantNumeric: 'tabular-nums' }}>
                          {formatAuditTime(u.last_login)}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">{relativeTime(u.last_login)}</Typography>
                      </Box>
                    </Tooltip>
                  ) : <Typography variant="body2" color="text.disabled">Hiç giriş yapmadı</Typography>}
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && !isFetching && (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 5, color: 'text.secondary' }}>
                  {users?.length ? 'Bu filtrelerle kullanıcı bulunamadı.' : 'Henüz kullanıcı yok.'}
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
      <UserDetailDrawer user={(users ?? []).find((u) => u.id === detailId) ?? null} teams={teams ?? []}
                        onClose={() => setDetailId(null)} onChanged={invalidate} />

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Kullanıcı Ekle</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Kullanıcı Adı" size="small" value={form.username} autoFocus
                       onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))} />
            <TextField select label="Kaynak" size="small" value={form.auth_source}
                       onChange={(e) => setForm((f) => ({ ...f, auth_source: e.target.value }))}
                       helperText={form.auth_source === 'ldap' ? 'LDAP ön kaydı: ad ve e-posta ilk girişte dizinden güncellenir' : undefined}>
              <MenuItem value="local">Lokal</MenuItem>
              <MenuItem value="ldap">LDAP (ön kayıt)</MenuItem>
            </TextField>
            {form.auth_source === 'local' && (
              <TextField label="Şifre" type="password" size="small" value={form.password}
                         onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} />
            )}
            <TextField label="Ad Soyad" size="small" value={form.full_name}
                       onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} />
            <TextField label="E-posta" size="small" value={form.email}
                       onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
            <TextField select label="Rol" size="small" value={form.role}
                       onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
                       helperText={ROLE_OPTIONS.find((o) => o.value === form.role)?.hint}>
              {ROLE_OPTIONS.map((o) => <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>)}
            </TextField>
            {(form.role === 'editor' || form.role === 'viewer') && (
              <Alert severity="info" sx={{ py: 0.5 }}>
                <b>{ROLE_CHIP[form.role].label}</b> takım-kapsamlıdır. Ekledikten sonra açılan detay panelinden bir
                {' '}<b>SY ekibine</b> atayın; aksi halde hiçbir veriyi göremez.
              </Alert>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Vazgeç</Button>
          <Button variant="contained" onClick={() => create.mutate()}
                  disabled={!form.username.trim() || (form.auth_source === 'local' && !form.password) || create.isPending}>
            Ekle
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  )
}
