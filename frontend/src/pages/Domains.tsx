import AddIcon from '@mui/icons-material/Add'
import CloseIcon from '@mui/icons-material/Close'
import DeleteIcon from '@mui/icons-material/DeleteOutlined'
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined'
import EditIcon from '@mui/icons-material/EditOutlined'
import FileDownloadIcon from '@mui/icons-material/FileDownloadOutlined'
import FileUploadIcon from '@mui/icons-material/FileUploadOutlined'
import GridViewIcon from '@mui/icons-material/GridView'
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown'
import TableRowsIcon from '@mui/icons-material/TableRows'
import VisibilityIcon from '@mui/icons-material/VisibilityOutlined'
import {
  Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, ListItemIcon, ListItemText,
  Menu, MenuItem, Skeleton, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  ToggleButton, ToggleButtonGroup, Tooltip, Typography,
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
import { CARD_SX } from '../components/DetailCards'
import { ActiveFilters, DaysLeftPill, Ellipsis, EmptyState, ListCard, RowMenu, SearchBox, StatusTabs } from '../components/ListKit'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { mappingTypeLabel } from '../theme'
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
  { key: 'client', label: 'Trusted', kind: 'status', options: STATUS_OPTS, get: (d) => certStatus(d.client_days_left) },
  { key: 'email', label: 'SY E-posta', kind: 'text', get: (d) => d.sy_team?.email },
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
  const [excelMenu, setExcelMenu] = useState<HTMLElement | null>(null)
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
    nocert: data?.counts.nocert ?? 0,
  }

  // Etkin filtrelerin çipleri — her biri tek tıkla kaldırılır
  const colChips = cf.defs.filter((c) => cf.active(c.key)).map((c) => {
    const v = cf.values[c.key]
    const shown = c.kind === 'status' ? (c.options?.find((o) => o.value === v)?.label ?? v) : `"${v}"`
    return { key: `f_${c.key}`, label: `${c.label}: ${shown}`, onDelete: () => cf.set(c.key, c.kind === 'status' ? 'all' : '') }
  })
  const chips = [
    ...(syFilter ? [{ key: 'sy', label: `SY Takımı: ${syFilter}`, onDelete: () => patchUrl({ sy: null }) }] : []),
    ...colChips,
  ]
  const filtered = !!search.trim() || status !== 'all' || chips.length > 0

  const serverCertOf = (d: Domain) =>
    d.certificates.find((c) => c.mapping_type === 'server' && c.days_left === d.server_days_left)
  const clientCertOf = (d: Domain) =>
    d.certificates.find((c) => c.mapping_type === 'client' && c.days_left === d.client_days_left)

  const rowMenu = (d: Domain) => (
    <RowMenu items={[
      { label: 'Detayı aç', icon: <VisibilityIcon fontSize="small" />, onClick: () => setDetailId(d.id) },
      { label: 'Düzenle', icon: <EditIcon fontSize="small" />, onClick: () => { setEditTarget(d); setFormOpen(true) }, hidden: !canEdit },
      { label: 'Sil', icon: <DeleteIcon fontSize="small" />, onClick: () => setDeleteTarget(d), danger: true, hidden: !canEdit },
    ]} />
  )

  return (
    <Box>
      <PageHeader
        title="Domainler"
        subtitle="Domain envanteri, sertifika bağlantıları ve canlı doğrulama"
        actions={
          <>
            <Button variant="outlined" color="inherit" startIcon={<FileDownloadIcon />}
                    endIcon={<KeyboardArrowDownIcon />} onClick={(e) => setExcelMenu(e.currentTarget)}
                    disabled={excelImport.isPending} sx={{ borderColor: 'divider' }}>
              Excel
            </Button>
            <Menu anchorEl={excelMenu} open={!!excelMenu} onClose={() => setExcelMenu(null)}
                  anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                  transformOrigin={{ vertical: 'top', horizontal: 'right' }}
                  slotProps={{ paper: { sx: { minWidth: 260, borderRadius: 2, border: 1, borderColor: 'divider' } } }}>
              <MenuItem onClick={() => { setExcelMenu(null); void handleExport() }}>
                <ListItemIcon><FileDownloadIcon fontSize="small" /></ListItemIcon>
                <ListItemText primary="Listeyi indir" secondary="Filtrelenen tüm domainler (.xlsx)" />
              </MenuItem>
              {canEdit && (
                <MenuItem onClick={() => { setExcelMenu(null); handleTemplateDownload() }}>
                  <ListItemIcon><DescriptionOutlinedIcon fontSize="small" /></ListItemIcon>
                  <ListItemText primary="Boş şablon indir" secondary="Başlıklar ve örnek satır" />
                </MenuItem>
              )}
              {canEdit && (
                <MenuItem onClick={() => { setExcelMenu(null); excelInput.current?.click() }}>
                  <ListItemIcon><FileUploadIcon fontSize="small" /></ListItemIcon>
                  <ListItemText primary="Excel'den yükle" secondary="Doldurulmuş şablonla toplu ekle" />
                </MenuItem>
              )}
            </Menu>
            {canEdit && (
              <Button variant="contained" startIcon={<AddIcon />} disableElevation
                      onClick={() => { setEditTarget(null); setFormOpen(true) }}>
                Yeni Domain
              </Button>
            )}
          </>
        }
      />
      <input ref={excelInput} type="file" hidden
             accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
             onChange={(e) => {
               const f = e.target.files?.[0]
               if (f) excelImport.mutate(f)
               e.target.value = ''
             }} />

      <ListCard
        busy={isFetching && !isLoading}
        tabs={
          <StatusTabs value={status} onChange={(v) => setStatus(v as StatusFilter)} items={[
            { value: 'all', label: 'Tümü', count: counts.total },
            { value: 'valid', label: 'Geçerli', count: counts.valid, tone: 'success' },
            { value: 'expiring', label: 'Yaklaşan (≤30g)', count: counts.expiring, tone: 'warning' },
            { value: 'expired', label: 'Süresi dolmuş', count: counts.expired, tone: 'error' },
            { value: 'nocert', label: 'Sertifikasız', count: counts.nocert },
          ]} />
        }
        toolbar={
          <>
            <SearchBox value={search} onChange={setSearch} placeholder="Domain, dış adres veya sertifika sahibi ara" width={380} />
            <Box sx={{ flexGrow: 1 }} />
            <Typography variant="body2" color="text.secondary" sx={{ fontVariantNumeric: 'tabular-nums' }}>
              {(data?.total ?? 0).toLocaleString('tr-TR')} domain
            </Typography>
            <ToggleButtonGroup size="small" exclusive value={view} onChange={(_, v) => v && setView(v)}>
              <ToggleButton value="table" aria-label="Tablo görünümü"><Tooltip title="Tablo görünümü"><TableRowsIcon fontSize="small" /></Tooltip></ToggleButton>
              <ToggleButton value="cards" aria-label="Kart görünümü"><Tooltip title="Kart görünümü"><GridViewIcon fontSize="small" /></Tooltip></ToggleButton>
            </ToggleButtonGroup>
          </>
        }
        chips={chips.length ? <ActiveFilters chips={chips} onClearAll={() => { patchUrl({ sy: null }); cf.clearAll() }} /> : undefined}
        footer={!isError && !isLoading && (data?.total ?? 0) > 0 && (
          <ListPagination total={data?.total ?? 0} page={paging.page} size={paging.size}
                          onPage={paging.setPage} onSize={paging.setSize} unit="domain" />
        )}
      >
        {isError ? (
          <Box sx={{ p: 2 }}><QueryError error={error} onRetry={() => refetch()} /></Box>
        ) : isLoading ? (
          <Box sx={{ p: 2 }}>{[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} height={44} />)}</Box>
        ) : items.length === 0 ? (
          <EmptyState
            title={filtered ? 'Bu filtrelerle eşleşen domain yok' : 'Henüz domain eklenmemiş'}
            hint={filtered ? 'Aramayı veya filtreleri değiştirmeyi deneyin.' : 'Yeni Domain ile ekleyin ya da Excel şablonuyla toplu yükleyin.'}
            action={filtered ? <Button size="small" onClick={() => { setSearch(''); setStatus('all'); patchUrl({ sy: null }); cf.clearAll() }}>Filtreleri temizle</Button> : undefined} />
        ) : view === 'cards' ? (
          <Box sx={{ p: 1.5, display: 'grid', gap: 1.5, gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', md: 'repeat(3, 1fr)', xl: 'repeat(4, 1fr)' } }}>
            {items.map((d) => {
              const st = domainStatus(d)
              const tone = st === 'expired' ? 'error.main' : st === 'expiring' ? 'warning.main' : st === 'valid' ? 'success.main' : 'divider'
              return (
                <Box key={d.id} onClick={() => setDetailId(d.id)}
                     sx={{ ...CARD_SX, p: 1.75, cursor: 'pointer', position: 'relative', overflow: 'hidden',
                           display: 'flex', flexDirection: 'column', gap: 1.25,
                           transition: 'border-color .15s, box-shadow .15s',
                           '&::before': { content: '""', position: 'absolute', left: 0, top: 0, bottom: 0, width: 3, bgcolor: tone },
                           '&:hover': { borderColor: 'text.disabled', boxShadow: 2 } }}>
                  <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
                    <Box sx={{ minWidth: 0, flexGrow: 1 }}>
                      <Typography noWrap title={d.domain} sx={{ fontWeight: 650 }}>{d.domain}</Typography>
                      <Typography variant="caption" color="text.secondary" noWrap component="div">
                        {d.sy_team?.name ?? 'SY atanmamış'}{(d.ug_team_name ?? d.ug_team?.name) ? ` · ${d.ug_team_name ?? d.ug_team?.name}` : ''}
                      </Typography>
                    </Box>
                    <Box onClick={(e) => e.stopPropagation()}>{rowMenu(d)}</Box>
                  </Box>
                  <Box sx={{ display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 1.5, rowGap: 0.75, alignItems: 'center' }}>
                    <Typography variant="caption" color="text.secondary">Server</Typography>
                    <Box><DaysLeftPill days={d.server_days_left} /></Box>
                    <Typography variant="caption" color="text.secondary">Trusted</Typography>
                    <Box><DaysLeftPill days={d.client_days_left} /></Box>
                  </Box>
                </Box>
              )
            })}
          </Box>
        ) : (
          <TableContainer sx={{ overflowX: 'auto' }}>
            <Table size="small" sx={{ minWidth: 1000, tableLayout: 'fixed' }}>
              <colgroup>
                <col style={{ width: '24%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '11%' }} />
                <col style={{ width: '23%' }} />
                <col style={{ width: '11%' }} />
                <col style={{ width: '13%' }} />
                <col style={{ width: 52 }} />
              </colgroup>
              <TableHead>
                <TableRow>
                  {COLS.map((c) => (
                    <ColHeaderCell key={c.key} def={c} cf={cf}
                                   sort={{ active: sort === c.key, direction: dir,
                                           onClick: () => toggleSort(c.key as SortKey) }} />
                  ))}
                  <TableCell aria-label="İşlemler" />
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((d) => {
                  const sc = serverCertOf(d)
                  const cc = clientCertOf(d)
                  return (
                    <TableRow key={d.id} hover onClick={() => setDetailId(d.id)} sx={{ cursor: 'pointer' }}>
                      <TableCell>
                        <Typography variant="body2" noWrap title={d.domain} sx={{ fontWeight: 600 }}>{d.domain}</Typography>
                        {d.external_address && (
                          <Typography variant="caption" color="text.secondary" noWrap component="div" title={d.external_address}>
                            {d.external_address}
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell><Ellipsis>{d.sy_team?.name ?? '—'}</Ellipsis></TableCell>
                      <TableCell><Ellipsis secondary>{d.ug_team_name ?? d.ug_team?.name ?? '—'}</Ellipsis></TableCell>
                      <TableCell><DaysLeftPill days={d.server_days_left} date={sc?.valid_to} /></TableCell>
                      <TableCell><Tooltip title={cc ? `${cc.name} · ${cc.valid_to ? new Date(cc.valid_to).toLocaleDateString('tr-TR') : ''}` : ''}>
                        <span><DaysLeftPill days={d.client_days_left} /></span>
                      </Tooltip></TableCell>
                      <TableCell><Ellipsis secondary>{d.sy_team?.email ?? '—'}</Ellipsis></TableCell>
                      <TableCell align="right" sx={{ px: 0.5 }} onClick={(e) => e.stopPropagation()}>{rowMenu(d)}</TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </ListCard>

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
