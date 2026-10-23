import AddIcon from '@mui/icons-material/Add'
import BusinessIcon from '@mui/icons-material/Business'
import CloseIcon from '@mui/icons-material/Close'
import DeleteIcon from '@mui/icons-material/Delete'
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined'
import EditIcon from '@mui/icons-material/Edit'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlineOutlined'
import FileDownloadIcon from '@mui/icons-material/FileDownload'
import FileUploadIcon from '@mui/icons-material/FileUpload'
import GridViewIcon from '@mui/icons-material/GridView'
import SearchIcon from '@mui/icons-material/Search'
import TableRowsIcon from '@mui/icons-material/TableRows'
import VerifiedIcon from '@mui/icons-material/Verified'
import VisibilityIcon from '@mui/icons-material/Visibility'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import {
  Box, Button, Card, CardActions, CardContent, Chip, Dialog, DialogActions, DialogContent,
  DialogTitle, Grid, IconButton, InputAdornment, LinearProgress, Link, MenuItem, Paper, Skeleton,
  Table, TableBody, TableCell, TableHead, TableRow, TextField, ToggleButton, ToggleButtonGroup,
  Tooltip, Typography,
} from '@mui/material'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useRef, useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { Domain, DomainPage } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { ColHeaderCell, ColumnFilterMenu, useColumnFilters, type ColDef } from '../components/ColumnFilters'
import DomainDetailDrawer from '../components/DomainDetailDrawer'
import DomainFormDialog from '../components/DomainFormDialog'
import ListPagination from '../components/ListPagination'
import PageHeader from '../components/PageHeader'
import QueryError from '../components/QueryError'
import StatCard from '../components/StatCard'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { daysLeftColor, daysLeftLabel, mappingTypeLabel } from '../theme'
import { exportSheet } from '../utils/exportSheet'
import { useDebounced, usePaging } from '../hooks/usePaging'
import { useUrlId, useUrlParams, useUrlPatch, useUrlState } from '../hooks/useUrlState'

type StatusFilter = 'all' | 'valid' | 'expiring' | 'expired' | 'nocert'

function domainStatus(d: Domain): StatusFilter {
  const days = d.server_days_left ?? d.client_days_left
  return certStatus(days)
}

// Tek bir "kalan gün" değerinin durumu — kart kenar rengi için (filtre/sayaç sunucuda).
function certStatus(days: number | null | undefined): StatusFilter {
  if (days === null || days === undefined) return 'nocert'
  if (days < 0) return 'expired'
  if (days <= 30) return 'expiring'
  return 'valid'
}

// Sıralanabilir kolonlar (sunucu tarafında sıralanır)
const SORTABLE = ['domain', 'sy', 'ug', 'server', 'client', 'email'] as const
type SortKey = (typeof SORTABLE)[number]

const STATUS_OPTS = [
  { value: 'all', label: 'Tümü' },
  { value: 'valid', label: 'Geçerli' },
  { value: 'expiring', label: 'Yaklaşan (≤30g)' },
  { value: 'expired', label: 'Süresi Dolmuş' },
  { value: 'nocert', label: 'Sertifikasız' },
]

// Domain tablosu kolon-başı (huni) filtreleri — metin kolonları + server/client durum kolonları.
const COLS: ColDef<Domain>[] = [
  { key: 'domain', label: 'Domain', kind: 'text', get: (d) => d.domain },
  { key: 'sy', label: 'SY Takımı', kind: 'text', get: (d) => d.sy_team?.name },
  { key: 'ug', label: 'UG Takımı', kind: 'text', get: (d) => d.ug_team_name ?? d.ug_team?.name },
  { key: 'server', label: 'Server Sertifika', kind: 'status', options: STATUS_OPTS, get: (d) => certStatus(d.server_days_left) },
  { key: 'client', label: 'Trusted Sertifika', kind: 'status', options: STATUS_OPTS, get: (d) => certStatus(d.client_days_left) },
  { key: 'email', label: 'E-Mail', kind: 'text', get: (d) => d.sy_team?.email },
]

export default function Domains() {
  useDocumentTitle('Domainler')
  const { canEdit } = useAuth()
  const { enqueueSnackbar, closeSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [view, setView] = useUrlState<'cards' | 'table'>('view', 'table', ['cards', 'table'])
  const [search, setSearch] = useUrlState<string>('q', '')
  const [status, setStatus] = useUrlState<StatusFilter>('status', 'all', ['all', 'valid', 'expiring', 'expired', 'nocert'])
  const cf = useColumnFilters(COLS, { urlPrefix: 'f_' })  // tablo kolon-başı (huni) filtreleri
  const [formOpen, setFormOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<Domain | null>(null)
  const [detailId, setDetailId] = useUrlId('domain')
  const [deleteTarget, setDeleteTarget] = useState<Domain | null>(null)
  const searchParams = useUrlParams()
  const patchUrl = useUrlPatch()
  const syFilter = searchParams.get('sy')
  const excelInput = useRef<HTMLInputElement>(null)
  const [sort, setSort] = useUrlState<SortKey>('sort', 'domain', SORTABLE)
  const [dir, setDir] = useUrlState<'asc' | 'desc'>('dir', 'asc', ['asc', 'desc'])
  const toggleSort = (key: SortKey) => {
    if (sort === key) setDir(dir === 'asc' ? 'desc' : 'asc')
    else { setSort(key); setDir('asc') }
  }

  // Arama / filtre / sıralama → sunucu sorgusu. Metin girişleri gecikmeli (her tuşta istek yok).
  const filterParams = useDebounced(JSON.stringify({
    q: search.trim() || undefined, status: status === 'all' ? undefined : status,
    sy: syFilter || undefined, sort, dir, ...cf.params,
  }))
  const paging = usePaging(filterParams)

  // 2.000+ domainde tüm listeyi çekmek sayfayı yavaşlatıyordu: sunucu yalnız görünen sayfayı döner.
  const { data, isLoading, isFetching, isError, error, refetch } = useQuery<DomainPage>({
    queryKey: ['domains', 'page', filterParams, paging.page, paging.size],
    queryFn: async () => (await api.get('/domains/page', {
      params: { ...JSON.parse(filterParams), page: paging.page, size: paging.size },
    })).data,
    placeholderData: keepPreviousData,
  })
  const items = data?.items ?? []

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => api.delete(`/domains/${id}`),
    onSuccess: () => {
      enqueueSnackbar('Domain silindi', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['domains'] })
      queryClient.invalidateQueries({ queryKey: ['domain-options'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      setDeleteTarget(null)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const excelImport = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return (await api.post('/domains/import-excel', form)).data
    },
    onSuccess: (d: { created: number; skipped: number; errors: string[] }) => {
      enqueueSnackbar(
        `${d.created} domain eklendi, ${d.skipped} atlandı${d.errors.length ? `, ${d.errors.length} hatalı satır` : ''}`,
        { variant: d.created > 0 ? 'success' : 'warning' },
      )
      if (d.errors.length) {
        // Eklenmeyen satırlar ekranda kalır: kullanıcı hangi ekibin bulunamadığını görüp düzeltsin
        const shown = d.errors.slice(0, 5)
        enqueueSnackbar(
          <div style={{ whiteSpace: 'pre-line' }}>
            {[...shown, ...(d.errors.length > shown.length ? [`… ve ${d.errors.length - shown.length} satır daha`] : [])].join('\n')}
          </div>,
          {
            variant: 'warning', persist: true,
            action: (key) => (
              <IconButton size="small" color="inherit" aria-label="Kapat" onClick={() => closeSnackbar(key)}>
                <CloseIcon fontSize="small" />
              </IconButton>
            ),
          },
        )
      }
      queryClient.invalidateQueries({ queryKey: ['domains'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['teams'] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const IMPORT_HEADERS = ['domain', 'sy', 'ug', 'external_address', 'cert_owner',
    'mail_addresses', 'external_company', 'info', 'lb_update', 'env_update', 'waf_update',
    'action_required', 'ssl_pinning', 'keystore', 'servers_to_update']
  const handleTemplateDownload = () => {
    exportSheet('domain-sablon.xlsx', IMPORT_HEADERS, [
      ['ornek.jumbo.local', 'Açık Bankacılık SY', 'Ödeme UG', '10.0.0.1', 'ornek@jumbo.local',
       'ops@jumbo.local', '', 'Örnek satır — silip kendi verinizi girin', 'Evet', 'Hayır',
       'Evet', 'Hayır', 'Hayır', '', ''],
    ])
  }

  const handleExport = async () => {
    // Filtrelenen TÜM kayıtlar (yalnız görünen sayfa değil) — sunucudan tek seferde alınır
    let visibleRows: Domain[]
    try {
      visibleRows = (await api.get<DomainPage>('/domains/page', {
        params: { ...JSON.parse(filterParams), all: true },
      })).data.items
    } catch (e) {
      enqueueSnackbar(apiErrorMessage(e), { variant: 'error' })
      return
    }
    // DB'deki tüm domain kolonları + türetilen alanlar — eksiksiz dışa aktarım
    exportSheet('domainler.xlsx',
      ['domain', 'external_address', 'sy', 'ug', 'cert_owner', 'external_company',
       'mail_addresses', 'expire_date', 'lb_update', 'waf_update', 'env_update',
       'servers_to_update', 'action_required', 'ssl_pinning', 'keystore', 'info',
       'server_kalan_gun', 'trusted_kalan_gun', 'sertifikalar',
       'canli_dogrulama', 'son_kontrol'],
      visibleRows.map((d) => [d.domain, d.external_address, d.sy_team?.name, d.ug_team_name ?? d.ug_team?.name,
                           d.cert_owner, d.external_company, d.mail_addresses, d.expire_date,
                           d.lb_update, d.waf_update, d.env_update, d.servers_to_update,
                           d.action_required, d.ssl_pinning, d.keystore, d.info,
                           d.server_days_left, d.client_days_left,
                           d.certificates.map((c) => `${c.name}(${mappingTypeLabel(c.mapping_type)})`).join(' '),
                           d.live_check_status, d.live_check_at]))
  }

  // Üst kartlar: aramayla eşleşen tüm domainler üzerinden (sunucu sayar)
  const counts = {
    total: data?.counts.total ?? 0,
    expired: data?.counts.expired ?? 0,
    expiring: data?.counts.expiring ?? 0,
    valid: data?.counts.valid ?? 0,
  }

  const actions = (d: Domain) => (
    <Box sx={{ display: 'inline-flex', flexWrap: 'nowrap', gap: 0.25, whiteSpace: 'nowrap' }}>
      <Tooltip title="Detay">
        <IconButton size="small" color="info" onClick={() => setDetailId(d.id)}>
          <VisibilityIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      {canEdit && (
        <>
          <Tooltip title="Düzenle">
            <IconButton size="small" color="primary" onClick={() => { setEditTarget(d); setFormOpen(true) }}>
              <EditIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Sil">
            <IconButton size="small" color="error" onClick={() => setDeleteTarget(d)}>
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </>
      )}
    </Box>
  )

  return (
    <Box>
      <PageHeader title="Domainler" subtitle="Domain envanteri, sertifika bağlantıları ve canlı doğrulama" />
      <Grid container spacing={2} sx={{ mb: 2 }}>
        {[
          { label: 'Toplam Domain', value: counts.total, color: '#42a5f5', icon: <BusinessIcon fontSize="large" />, status: 'all' as const },
          { label: 'Süresi Dolmuş', value: counts.expired, color: '#ef5350', icon: <ErrorOutlineIcon fontSize="large" />, status: 'expired' as const },
          { label: 'Yaklaşan (≤30g)', value: counts.expiring, color: '#ffa726', icon: <WarningAmberIcon fontSize="large" />, status: 'expiring' as const },
          { label: 'Geçerli', value: counts.valid, color: '#66bb6a', icon: <VerifiedIcon fontSize="large" />, status: 'valid' as const },
        ].map((s) => (
          <Grid key={s.label} size={{ xs: 6, md: 3 }}>
            <StatCard icon={s.icon} label={s.label} value={s.value} color={s.color}
                      onClick={() => setStatus(s.status)} />
          </Grid>
        ))}
      </Grid>

      <Box sx={{ display: 'flex', gap: 2, mb: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        {canEdit && (
          <Button variant="contained" startIcon={<AddIcon />}
                  onClick={() => { setEditTarget(null); setFormOpen(true) }}>
            Yeni Ekle
          </Button>
        )}
        <TextField
          size="small" placeholder="Ara…" value={search} onChange={(e) => setSearch(e.target.value)}
          sx={{ width: 260 }}
          slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment> } }}
        />
        <TextField select size="small" label="Durum" value={status} sx={{ width: 170 }}
                   onChange={(e) => setStatus(e.target.value as StatusFilter)}>
          <MenuItem value="all">Tümü</MenuItem>
          <MenuItem value="valid">Geçerli</MenuItem>
          <MenuItem value="expiring">Yaklaşan (≤30g)</MenuItem>
          <MenuItem value="expired">Süresi Dolmuş</MenuItem>
          <MenuItem value="nocert">Sertifikasız</MenuItem>
        </TextField>
        {syFilter && (
          <Chip label={`SY: ${syFilter}`} color="success" onDelete={() => patchUrl({ sy: null })} />
        )}
        {cf.anyActive && (
          <Chip label="Kolon filtreleri" color="primary" variant="outlined" onDelete={cf.clearAll} />
        )}
        <Box sx={{ flexGrow: 1 }} />
        <Typography variant="body2" color="text.secondary">
          {data?.total ?? 0} / {counts.total} domain
        </Typography>
        <Tooltip title="Görünen listeyi Excel (.xlsx) olarak indirir">
          <Button size="small" variant="outlined" color="inherit" startIcon={<FileDownloadIcon />}
                  onClick={handleExport}>Excel İndir</Button>
        </Tooltip>
        {canEdit && (
          <>
            <Tooltip title="Boş şablonu (başlıklar + örnek satır) indirir">
              <Button size="small" variant="outlined" color="inherit" startIcon={<DescriptionOutlinedIcon />}
                      onClick={handleTemplateDownload}>
                Şablon İndir
              </Button>
            </Tooltip>
            <Tooltip title="Excel'den toplu domain ekler (1. satır başlık; şablonu doldurup yükleyin)">
              <Button size="small" variant="outlined" color="inherit" startIcon={<FileUploadIcon />}
                      onClick={() => excelInput.current?.click()} disabled={excelImport.isPending}>
                Excel Yükle
              </Button>
            </Tooltip>
          </>
        )}
        <input ref={excelInput} type="file" hidden
               accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
               onChange={(e) => {
                 const f = e.target.files?.[0]
                 if (f) excelImport.mutate(f)
                 e.target.value = ''
               }} />
        <ToggleButtonGroup size="small" exclusive value={view} onChange={(_, v) => v && setView(v)}>
          <ToggleButton value="cards"><Tooltip title="Kart görünümü"><GridViewIcon fontSize="small" /></Tooltip></ToggleButton>
          <ToggleButton value="table"><Tooltip title="Tablo görünümü"><TableRowsIcon fontSize="small" /></Tooltip></ToggleButton>
        </ToggleButtonGroup>
      </Box>

      <LinearProgress sx={{ mb: 0.5, height: 2, visibility: isFetching && !isLoading ? 'visible' : 'hidden' }} />
      {isError ? (
        <QueryError error={error} onRetry={() => refetch()} />
      ) : isLoading ? (
        <Skeleton variant="rounded" height={400} />
      ) : view === 'cards' ? (
        <Grid container spacing={2}>
          {items.map((d) => {
            const st = domainStatus(d)
            return (
              <Grid key={d.id} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
                <Card variant="outlined"
                      sx={{ height: '100%', display: 'flex', flexDirection: 'column',
                            borderColor: st === 'expired' ? 'error.main' : st === 'expiring' ? 'warning.main' : 'divider' }}>
                  <CardContent sx={{ pb: 1, flexGrow: 1 }}>
                    <Link component="button" underline="hover" color="inherit" noWrap title={d.domain}
                          onClick={() => setDetailId(d.id)}
                          sx={{ display: 'block', maxWidth: '100%', textAlign: 'left', fontWeight: 700, fontSize: 16 }}>
                      {d.domain}
                    </Link>
                    <Box sx={{ display: 'flex', gap: 1, mt: 1, flexWrap: 'wrap' }}>
                      <Chip size="small" color={daysLeftColor(d.server_days_left)}
                            label={`Server: ${d.server_days_left != null ? daysLeftLabel(d.server_days_left) : '—'}`} />
                      <Chip size="small" variant="outlined" color={daysLeftColor(d.client_days_left)}
                            label={`Trusted: ${d.client_days_left != null ? daysLeftLabel(d.client_days_left) : '—'}`} />
                    </Box>
                    <Box sx={{ display: 'flex', gap: 1, mt: 1, flexWrap: 'wrap' }}>
                      {d.sy_team?.email && (
                        <Chip size="small" variant="outlined" label={d.sy_team.email.split(',')[0]} />
                      )}
                      {d.sy_team && <Chip size="small" variant="outlined" label={`SY: ${d.sy_team.name}`} color="success" />}
                      {(d.ug_team_name ?? d.ug_team?.name) && <Chip size="small" variant="outlined" label={`UG: ${d.ug_team_name ?? d.ug_team?.name}`} color="secondary" />}
                    </Box>
                  </CardContent>
                  <CardActions>{actions(d)}</CardActions>
                </Card>
              </Grid>
            )
          })}
          {items.length === 0 && (
            <Grid size={{ xs: 12 }}>
              <Paper sx={{ p: 6, textAlign: 'center' }}>
                <Typography color="text.secondary">Filtreyle eşleşen domain yok</Typography>
              </Paper>
            </Grid>
          )}
        </Grid>
      ) : (
        <Paper>
          <Table size="small">
            <TableHead>
              <TableRow>
                {COLS.map((c) => (
                  <ColHeaderCell key={c.key} def={c} cf={cf}
                                 sort={{ active: sort === c.key, direction: dir,
                                         onClick: () => toggleSort(c.key as SortKey) }} />
                ))}
                <TableCell align="right">İşlemler</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {items.map((d) => (
                <TableRow key={d.id} hover>
                  <TableCell sx={{ fontWeight: 600 }}>
                    <Link component="button" underline="hover" color="inherit" onClick={() => setDetailId(d.id)}
                          sx={{ fontWeight: 600, textAlign: 'left' }}>
                      {d.domain}
                    </Link>
                  </TableCell>
                  <TableCell>{d.sy_team?.name ?? '—'}</TableCell>
                  <TableCell>{d.ug_team_name ?? d.ug_team?.name ?? '—'}</TableCell>
                  <TableCell>
                    <Chip size="small" color={daysLeftColor(d.server_days_left)}
                          label={d.server_days_left != null ? daysLeftLabel(d.server_days_left) : '—'} />
                  </TableCell>
                  <TableCell>
                    <Chip size="small" variant="outlined" color={daysLeftColor(d.client_days_left)}
                          label={d.client_days_left != null ? daysLeftLabel(d.client_days_left) : '—'} />
                  </TableCell>
                  <TableCell sx={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {d.sy_team?.email ?? '—'}
                  </TableCell>
                  <TableCell align="right" sx={{ whiteSpace: 'nowrap', width: '1%' }}>{actions(d)}</TableCell>
                </TableRow>
              ))}
              {items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7}>
                    <Typography color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
                      Filtreyle eşleşen domain yok
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </Paper>
      )}

      {!isError && !isLoading && (
        <ListPagination total={data?.total ?? 0} page={paging.page} size={paging.size}
                        onPage={paging.setPage} onSize={paging.setSize} unit="domain" />
      )}

      <ColumnFilterMenu cf={cf} facetCounts={data?.facets} />

      <DomainFormDialog open={formOpen} onClose={() => setFormOpen(false)} domain={editTarget} />
      <DomainDetailDrawer domainId={detailId} onClose={() => setDetailId(null)} />

      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>Domain Sil</DialogTitle>
        <DialogContent>
          <Typography><b>{deleteTarget?.domain}</b> ve sertifika bağlantıları silinecek. Emin misiniz?</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Vazgeç</Button>
          <Button color="error" variant="contained"
                  onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}>
            Sil
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
