import BlockIcon from '@mui/icons-material/Block'
import InventoryIcon from '@mui/icons-material/Inventory2'
import PlaylistAddCheckIcon from '@mui/icons-material/PlaylistAddCheck'
import PublicIcon from '@mui/icons-material/Public'
import RadarIcon from '@mui/icons-material/Radar'
import TaskAltIcon from '@mui/icons-material/TaskAlt'
import TravelExploreIcon from '@mui/icons-material/TravelExplore'
import VisibilityIcon from '@mui/icons-material/Visibility'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import {
  Alert, Box, Button, Chip, Grid, IconButton, Paper, Skeleton, Stack, Table, TableBody, TableCell,
  TableHead, TableRow, Tooltip, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { DiscoveredCertificate, DiscoveryStatus, ScanRun } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import DiscoveredCertificateDetailDrawer from '../components/DiscoveredCertificateDetailDrawer'
import PageHeader from '../components/PageHeader'
import QueryError from '../components/QueryError'
import StatCard from '../components/StatCard'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { usePageAccess } from '../hooks/usePageAccess'
import { MONO_FONT, daysLeftColor, daysLeftLabel } from '../theme'

const STATUS_META: Record<DiscoveryStatus, { label: string; color: 'warning' | 'success' | 'info' | 'default' }> = {
  new: { label: 'Bilinmeyen', color: 'warning' },
  in_inventory: { label: 'Envanterde', color: 'success' },
  adopted: { label: 'Envantere Alındı', color: 'info' },
  ignored: { label: 'Yok sayıldı', color: 'default' },
}

function fmtRun(run: ScanRun): string {
  const when = new Date(run.started_at).toLocaleString('tr-TR')
  if (run.status === 'running') return `${when} — taranıyor…`
  if (run.status === 'error') return `${when} — HATA: ${run.error ?? ''}`
  return `${when} — ${run.hosts_reachable} erişilebilir endpoint, ${run.new_findings} yeni bilinmeyen`
}

export default function Discovery() {
  useDocumentTitle('Keşif')
  const { canEdit, isAdmin } = useAuth()
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [detailId, setDetailId] = useState<number | null>(null)
  const [filter, setFilter] = useState<DiscoveryStatus | null>(null)
  const [originFilter, setOriginFilter] = useState<'network' | 'ct' | null>(null)

  const { data: runs } = useQuery<ScanRun[]>({
    queryKey: ['discovery', 'runs'],
    queryFn: async () => (await api.get('/discovery/runs', { params: { limit: 5 } })).data,
    refetchInterval: (q) => (q.state.data?.[0]?.status === 'running' ? 5000 : false),
  })
  const scanning = runs?.[0]?.status === 'running'

  const { data: findings, isLoading, isError, error, refetch } = useQuery<DiscoveredCertificate[]>({
    queryKey: ['discovery', 'findings'],
    queryFn: async () => (await api.get('/discovery/findings')).data,
    refetchInterval: scanning ? 5000 : false,
  })

  const counts = useMemo(() => {
    const c = { total: 0, new: 0, in_inventory: 0, adopted: 0, ignored: 0 }
    for (const f of findings ?? []) { c.total++; c[f.status]++ }
    return c
  }, [findings])

  const rows = (findings ?? []).filter((f) => (filter ? f.status === filter : true))
                               .filter((f) => (originFilter ? f.origin === originFilter : true))
  const hasCt = (findings ?? []).some((f) => f.origin === 'ct')

  // Tarama TAMAMLANINCA sonucu bildir (arka planda çalışır). Açılışta mevcut son çalıştırmayı
  // "duyurulmuş" sayarak eski taramayı her sayfa açılışında bildirmekten kaçınırız.
  const announcedRunRef = useRef<number | null | undefined>(undefined)
  useEffect(() => {
    if (runs === undefined) return
    const latest = runs[0]
    if (announcedRunRef.current === undefined) {
      announcedRunRef.current = latest?.id ?? null   // ilk yükleme: sessiz
      return
    }
    if (!latest || latest.status === 'running' || announcedRunRef.current === latest.id) return
    announcedRunRef.current = latest.id
    if (latest.status === 'error') {
      enqueueSnackbar(`Tarama hatası: ${latest.error ?? 'bilinmeyen'}`, { variant: 'error' })
    } else if (latest.new_findings > 0) {
      enqueueSnackbar(`Tarama tamamlandı — ${latest.new_findings} yeni bilinmeyen sertifika bulundu`,
                      { variant: 'warning' })
    } else if (latest.hosts_reachable === 0) {
      enqueueSnackbar("Tarama tamamlandı — hiçbir endpoint'e erişilemedi (hedef/erişim izinlerini kontrol edin)",
                      { variant: 'info' })
    } else {
      enqueueSnackbar('Tarama tamamlandı — envanterde olmayan yeni sertifika bulunamadı',
                      { variant: 'success' })
    }
  }, [runs, enqueueSnackbar])

  const scan = useMutation({
    mutationFn: async () => (await api.post('/discovery/scan')).data,
    onSuccess: (d) => {
      enqueueSnackbar(d.message ?? 'Tarama başlatıldı', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['discovery'] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const ctScan = useMutation({
    mutationFn: async () => (await api.post('/discovery/ct-scan')).data,
    onSuccess: (d) => {
      enqueueSnackbar(d.message ?? 'CT taraması başlatıldı', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['discovery'] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const act = useMutation({
    mutationFn: async ({ id, action }: { id: number; action: 'adopt' | 'ignore' }) =>
      (await api.post(`/discovery/findings/${id}/${action}`)).data,
    onSuccess: (d, v) => {
      enqueueSnackbar(v.action === 'adopt' ? (d.message ?? 'Envantere alındı') : 'Bulgu yok sayıldı',
                      { variant: v.action === 'adopt' ? 'success' : 'info' })
      // adopt envanteri değiştirir → sertifika listelerini de tazele (çoğul + tekil cache tuzağı)
      queryClient.invalidateQueries({ queryKey: ['discovery'] })
      queryClient.invalidateQueries({ queryKey: ['certificates'] })
      queryClient.invalidateQueries({ queryKey: ['certificate'] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  return (
    <Box>
      <PageHeader
        title="Keşif"
        subtitle="Ağ taraması ve Certificate Transparency (crt.sh) ile envanterde olmayan (shadow) sertifikaları yakalar"
        actions={isAdmin && (
          <Stack direction="row" spacing={1}>
            <Button variant="contained" startIcon={<RadarIcon />} disabled={scan.isPending || scanning}
                    onClick={() => scan.mutate()}>
              {scanning ? 'Taranıyor…' : 'Ağ Taraması'}
            </Button>
            <Tooltip title="Certificate Transparency loglarını (crt.sh) tarar — dış internet/proxy erişimi gerekir">
              <span>
                <Button variant="outlined" startIcon={<PublicIcon />} disabled={ctScan.isPending || scanning}
                        onClick={() => ctScan.mutate()}>
                  CT Taraması
                </Button>
              </span>
            </Tooltip>
          </Stack>
        )}
      />

      <Alert severity="info" icon={<TravelExploreIcon />} sx={{ mb: 2 }}>
        Keşif iki kaynaktan beslenir: <b>Ağ taraması</b> tanımlı hedeflere TLS bağlanır; <b>CT taraması</b>
        (crt.sh) sertifika şeffaflık loglarını okur (dış internet/proxy gerekir). Kaynakları ve gece
        taramasını <b>Ayarlar → Keşif</b> ve <b>Ayarlar → CT</b> sekmelerinden yönetin. "Bilinmeyen"
        bulgular envanterde olmayan sertifikalardır — inceleyip <b>Envantere Al</b> veya <b>Yok say</b>abilirsiniz.
      </Alert>

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard icon={<InventoryIcon />} label="Toplam Bulgu" value={counts.total} color="#607d8b"
                    onClick={() => setFilter(null)} />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard icon={<WarningAmberIcon />} label="Bilinmeyen (shadow)" value={counts.new} color="#f57c00"
                    onClick={() => setFilter('new')} />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard icon={<TaskAltIcon />} label="Envanterde" value={counts.in_inventory} color="#2e7d32"
                    onClick={() => setFilter('in_inventory')} />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard icon={<PlaylistAddCheckIcon />} label="Envantere Alınan" value={counts.adopted} color="#1565c0"
                    onClick={() => setFilter('adopted')} />
        </Grid>
      </Grid>

      {runs?.[0] && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          <b>Son tarama:</b> {fmtRun(runs[0])} {runs[0].kind === 'ct' ? '(CT)' : '(Ağ)'}
          {filter && (
            <Chip size="small" variant="outlined" label={`Filtre: ${STATUS_META[filter].label} · temizle`}
                  onDelete={() => setFilter(null)} onClick={() => setFilter(null)} sx={{ ml: 1.5 }} />
          )}
        </Typography>
      )}

      {hasCt && (
        <Stack direction="row" spacing={1} sx={{ mb: 1.5 }}>
          <Typography variant="body2" color="text.secondary" sx={{ alignSelf: 'center' }}>Kaynak:</Typography>
          {([['Hepsi', null], ['Ağ', 'network'], ['CT Log', 'ct']] as const).map(([label, val]) => (
            <Chip key={label} size="small" label={label}
                  color={originFilter === val ? 'primary' : 'default'}
                  variant={originFilter === val ? 'filled' : 'outlined'}
                  onClick={() => setOriginFilter(val)} />
          ))}
        </Stack>
      )}

      <Paper variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Kaynak</TableCell>
              <TableCell>Endpoint / Domain</TableCell>
              <TableCell>Sertifika (CN)</TableCell>
              <TableCell>Issuer (CA)</TableCell>
              <TableCell>Bitiş</TableCell>
              <TableCell>Durum</TableCell>
              <TableCell align="right">İşlem</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {isError && (
              <TableRow><TableCell colSpan={7}>
                <QueryError error={error} onRetry={() => refetch()} />
              </TableCell></TableRow>
            )}
            {!isError && isLoading && [0, 1, 2].map((i) => (
              <TableRow key={i}><TableCell colSpan={7}><Skeleton height={32} /></TableCell></TableRow>
            ))}
            {!isError && !isLoading && rows.length === 0 && (
              <TableRow><TableCell colSpan={7} align="center" sx={{ py: 6 }}>
                <TravelExploreIcon sx={{ fontSize: 40, color: 'text.disabled', mb: 1 }} />
                <Typography color="text.secondary">
                  {counts.total === 0
                    ? 'Henüz bulgu yok — Ayarlar → Keşif\'ten hedef ekleyip taramayı başlatın.'
                    : 'Bu filtreye uyan bulgu yok.'}
                </Typography>
              </TableCell></TableRow>
            )}
            {rows.map((f) => (
              <TableRow key={f.id} hover>
                <TableCell>
                  <Chip size="small" variant="outlined"
                        icon={f.origin === 'ct' ? <PublicIcon /> : <RadarIcon />}
                        label={f.origin === 'ct' ? 'CT Log' : 'Ağ'}
                        color={f.origin === 'ct' ? 'secondary' : 'default'} />
                </TableCell>
                <TableCell sx={{ fontFamily: MONO_FONT, fontSize: 13, whiteSpace: 'nowrap' }}>
                  {f.origin === 'ct' ? f.host : `${f.host}:${f.port}`}
                </TableCell>
                <TableCell sx={{ fontWeight: 600, wordBreak: 'break-word' }}>{f.name || '—'}</TableCell>
                <TableCell sx={{ color: 'text.secondary', maxWidth: 260, wordBreak: 'break-word' }}>
                  {f.issuer || '—'}
                </TableCell>
                <TableCell>
                  <Chip size="small" color={daysLeftColor(f.days_left)} label={daysLeftLabel(f.days_left)} />
                </TableCell>
                <TableCell>
                  <Chip size="small" color={STATUS_META[f.status].color} label={STATUS_META[f.status].label} />
                </TableCell>
                <TableCell align="right" sx={{ whiteSpace: 'nowrap', width: '1%' }}>
                  <Box sx={{ display: 'inline-flex', flexWrap: 'nowrap', gap: 0.25, whiteSpace: 'nowrap' }}>
                    <Tooltip title="Detay">
                      <IconAction color="info" onClick={() => setDetailId(f.id)}>
                        <VisibilityIcon fontSize="small" />
                      </IconAction>
                    </Tooltip>
                    {canEdit && f.status !== 'adopted' && (
                      <Tooltip title="Envantere Al">
                        <IconAction color="success" disabled={act.isPending}
                                    onClick={() => act.mutate({ id: f.id, action: 'adopt' })}>
                          <PlaylistAddCheckIcon fontSize="small" />
                        </IconAction>
                      </Tooltip>
                    )}
                    {canEdit && f.status !== 'ignored' && (
                      <Tooltip title="Yok say">
                        <IconAction color="warning" disabled={act.isPending}
                                    onClick={() => act.mutate({ id: f.id, action: 'ignore' })}>
                          <BlockIcon fontSize="small" />
                        </IconAction>
                      </Tooltip>
                    )}
                  </Box>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>

      <DiscoveredCertificateDetailDrawer findingId={detailId} onClose={() => setDetailId(null)} />
    </Box>
  )
}

// Aksiyon ikonu (kayma önleyici nowrap kutuda) — küçük IconButton sarmalayıcı
function IconAction({ color, onClick, disabled, children }: {
  color: 'info' | 'success' | 'warning' | 'error'
  onClick: () => void
  disabled?: boolean
  children: ReactNode
}) {
  return (
    <IconButton size="small" color={color} onClick={onClick} disabled={disabled}>
      {children}
    </IconButton>
  )
}

// Nav rozeti: envanterde olmayan (shadow) bulgu sayısı — yalnız Keşif'i görebilenler sorgular
export function useDiscoveredCount() {
  const { discovery: canSee } = usePageAccess()
  const { data } = useQuery<DiscoveredCertificate[]>({
    queryKey: ['discovery', 'findings'],
    queryFn: async () => (await api.get('/discovery/findings')).data,
    enabled: canSee,
    refetchInterval: 60_000,
  })
  return (data ?? []).filter((f) => f.status === 'new').length
}
