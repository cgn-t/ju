import AddIcon from '@mui/icons-material/Add'
import BusinessIcon from '@mui/icons-material/Business'
import DeleteIcon from '@mui/icons-material/Delete'
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
  DialogTitle, Grid, IconButton, InputAdornment, MenuItem, Paper, Skeleton, Table, TableBody,
  TableCell, TableHead, TableRow, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, apiErrorMessage } from '../api/client'
import type { Domain } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import DomainDetailDrawer from '../components/DomainDetailDrawer'
import DomainFormDialog from '../components/DomainFormDialog'
import PageHeader from '../components/PageHeader'
import QueryError from '../components/QueryError'
import StatCard from '../components/StatCard'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { daysLeftColor, daysLeftLabel } from '../theme'
import { exportCsv } from '../utils/csv'

type StatusFilter = 'all' | 'valid' | 'expiring' | 'expired' | 'nocert'

function domainStatus(d: Domain): StatusFilter {
  const days = d.server_days_left ?? d.client_days_left
  if (days === null || days === undefined) return 'nocert'
  if (days < 0) return 'expired'
  if (days <= 30) return 'expiring'
  return 'valid'
}

export default function Domains() {
  useDocumentTitle('Domainler')
  const { canEdit } = useAuth()
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [view, setView] = useState<'cards' | 'table'>('cards')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [formOpen, setFormOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<Domain | null>(null)
  const [detailId, setDetailId] = useState<number | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Domain | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const syFilter = searchParams.get('sy')
  const csvInput = useRef<HTMLInputElement>(null)

  const { data: domains, isLoading, isError, error, refetch } = useQuery<Domain[]>({
    queryKey: ['domains', search],
    queryFn: async () => (await api.get('/domains', { params: { search: search || undefined } })).data,
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => api.delete(`/domains/${id}`),
    onSuccess: () => {
      enqueueSnackbar('Domain silindi', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['domains'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      setDeleteTarget(null)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const csvImport = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return (await api.post('/domains/import-csv', form)).data
    },
    onSuccess: (d: { created: number; skipped: number; errors: string[] }) => {
      enqueueSnackbar(
        `${d.created} domain eklendi, ${d.skipped} atlandı${d.errors.length ? `, ${d.errors.length} hatalı satır` : ''}`,
        { variant: d.created > 0 ? 'success' : 'warning' },
      )
      if (d.errors.length) console.warn('CSV import hataları:', d.errors)
      queryClient.invalidateQueries({ queryKey: ['domains'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['teams'] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const filtered = useMemo(
    () => (domains ?? []).filter((d) =>
      (status === 'all' || domainStatus(d) === status) &&
      (!syFilter || d.sy_team?.name === syFilter)),
    [domains, status, syFilter],
  )

  const handleExport = () => {
    // DB'deki tüm domain kolonları + türetilen alanlar — eksiksiz dışa aktarım
    exportCsv('domainler.csv',
      ['domain', 'external_address', 'sy', 'ug', 'cert_owner', 'external_company',
       'mail_addresses', 'expire_date', 'lb_update', 'waf_update', 'env_update',
       'servers_to_update', 'action_required', 'ssl_pinning', 'keystore', 'info',
       'server_kalan_gun', 'client_kalan_gun', 'sertifikalar',
       'canli_dogrulama', 'son_kontrol'],
      filtered.map((d) => [d.domain, d.external_address, d.sy_team?.name, d.ug_team_name ?? d.ug_team?.name,
                           d.cert_owner, d.external_company, d.mail_addresses, d.expire_date,
                           d.lb_update, d.waf_update, d.env_update, d.servers_to_update,
                           d.action_required, d.ssl_pinning, d.keystore, d.info,
                           d.server_days_left, d.client_days_left,
                           d.certificates.map((c) => `${c.name}(${c.mapping_type})`).join(' '),
                           d.live_check_status, d.live_check_at]))
  }

  const counts = useMemo(() => {
    const all = domains ?? []
    return {
      total: all.length,
      expired: all.filter((d) => domainStatus(d) === 'expired').length,
      expiring: all.filter((d) => domainStatus(d) === 'expiring').length,
      valid: all.filter((d) => domainStatus(d) === 'valid').length,
    }
  }, [domains])

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
      <PageHeader title="Domainler" subtitle="Domain envanteri, sertifika eşlemeleri ve canlı doğrulama" />
      <Grid container spacing={2} sx={{ mb: 2 }}>
        {[
          { label: 'Toplam Domain', value: counts.total, color: '#42a5f5', icon: <BusinessIcon fontSize="large" /> },
          { label: 'Süresi Dolmuş', value: counts.expired, color: '#ef5350', icon: <ErrorOutlineIcon fontSize="large" /> },
          { label: 'Yaklaşan (≤30g)', value: counts.expiring, color: '#ffa726', icon: <WarningAmberIcon fontSize="large" /> },
          { label: 'Geçerli', value: counts.valid, color: '#66bb6a', icon: <VerifiedIcon fontSize="large" /> },
        ].map((s) => (
          <Grid key={s.label} size={{ xs: 6, md: 3 }}>
            <StatCard icon={s.icon} label={s.label} value={s.value} color={s.color} />
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
          <Chip label={`SY: ${syFilter}`} color="success" onDelete={() => setSearchParams({})} />
        )}
        <Box sx={{ flexGrow: 1 }} />
        <Typography variant="body2" color="text.secondary">
          {filtered.length} / {counts.total} domain
        </Typography>
        <Tooltip title="Görünen listeyi CSV olarak indirir">
          <Button size="small" variant="outlined" color="inherit" startIcon={<FileDownloadIcon />}
                  onClick={handleExport}>CSV İndir</Button>
        </Tooltip>
        {canEdit && (
          <Tooltip title="CSV'den toplu domain ekler (kolonlar: domain, sy, ug, mail_addresses, …)">
            <Button size="small" variant="outlined" color="inherit" startIcon={<FileUploadIcon />}
                    onClick={() => csvInput.current?.click()} disabled={csvImport.isPending}>
              CSV Yükle
            </Button>
          </Tooltip>
        )}
        <input ref={csvInput} type="file" hidden accept=".csv,text/csv"
               onChange={(e) => {
                 const f = e.target.files?.[0]
                 if (f) csvImport.mutate(f)
                 e.target.value = ''
               }} />
        <ToggleButtonGroup size="small" exclusive value={view} onChange={(_, v) => v && setView(v)}>
          <ToggleButton value="cards"><Tooltip title="Kart görünümü"><GridViewIcon fontSize="small" /></Tooltip></ToggleButton>
          <ToggleButton value="table"><Tooltip title="Tablo görünümü"><TableRowsIcon fontSize="small" /></Tooltip></ToggleButton>
        </ToggleButtonGroup>
      </Box>

      {isError ? (
        <QueryError error={error} onRetry={() => refetch()} />
      ) : isLoading ? (
        <Skeleton variant="rounded" height={400} />
      ) : view === 'cards' ? (
        <Grid container spacing={2}>
          {filtered.map((d) => {
            const st = domainStatus(d)
            return (
              <Grid key={d.id} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
                <Card variant="outlined"
                      sx={{ height: '100%', display: 'flex', flexDirection: 'column',
                            borderColor: st === 'expired' ? 'error.main' : st === 'expiring' ? 'warning.main' : 'divider' }}>
                  <CardContent sx={{ pb: 1, flexGrow: 1 }}>
                    <Typography noWrap title={d.domain} sx={{ fontWeight: 700 }}>{d.domain}</Typography>
                    <Box sx={{ display: 'flex', gap: 1, mt: 1, flexWrap: 'wrap' }}>
                      <Chip size="small" color={daysLeftColor(d.server_days_left)}
                            label={`Server: ${d.server_days_left != null ? daysLeftLabel(d.server_days_left) : '—'}`} />
                      <Chip size="small" variant="outlined" color={daysLeftColor(d.client_days_left)}
                            label={`Client: ${d.client_days_left != null ? daysLeftLabel(d.client_days_left) : '—'}`} />
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
          {filtered.length === 0 && (
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
                <TableCell>Domain</TableCell>
                <TableCell>SY Takımı</TableCell>
                <TableCell>UG Takımı</TableCell>
                <TableCell>Server Sertifika</TableCell>
                <TableCell>Client Sertifika</TableCell>
                <TableCell>E-Mail</TableCell>
                <TableCell align="right">İşlemler</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filtered.map((d) => (
                <TableRow key={d.id} hover>
                  <TableCell sx={{ fontWeight: 600 }}>{d.domain}</TableCell>
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
            </TableBody>
          </Table>
        </Paper>
      )}

      <DomainFormDialog open={formOpen} onClose={() => setFormOpen(false)} domain={editTarget} />
      <DomainDetailDrawer domainId={detailId} onClose={() => setDetailId(null)} />

      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>Domain Sil</DialogTitle>
        <DialogContent>
          <Typography><b>{deleteTarget?.domain}</b> ve sertifika eşlemeleri silinecek. Emin misiniz?</Typography>
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
