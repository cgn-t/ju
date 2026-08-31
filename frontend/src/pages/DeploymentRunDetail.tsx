import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import CancelIcon from '@mui/icons-material/Cancel'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import ReplayIcon from '@mui/icons-material/Replay'
import RestartAltIcon from '@mui/icons-material/RestartAlt'
import {
  Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Paper, Stack,
  Table, TableBody, TableCell, TableHead, TableRow, Tooltip, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useState } from 'react'
import { Link as RouterLink, useNavigate, useParams } from 'react-router-dom'
import { api, apiErrorMessage } from '../api/client'
import type { Application, DeploymentRun } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import PageHeader from '../components/PageHeader'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { formatDuration } from '../utils/duration'
import { StatusChip, TRIGGER_TYPE_LABELS } from './Deployments'

/** Bir çalıştırmanın (run) tam detayı — Jenkins/GitHub Actions'taki "build listesi → build
 * detayı" deseniyle aynı: Dağıtım sayfasındaki özet listeden satıra tıklayarak ulaşılır, ana
 * menüde YER ALMAZ. Bu sayfa öncesinde Dağıtım sayfasına sıkışmış inline tabloydu — kullanıcı
 * geri bildirimi: parametreler hiç görünmüyordu, bu da hangi geçmiş run'ın rollback için doğru
 * aday olduğunu anlamayı zorlaştırıyordu. */
export default function DeploymentRunDetail() {
  const { runId } = useParams<{ runId: string }>()
  const id = Number(runId)
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
  const { enqueueSnackbar } = useSnackbar()
  const qc = useQueryClient()

  const { data: run, isLoading } = useQuery<DeploymentRun>({
    queryKey: ['deployment-run', id],
    queryFn: async () => (await api.get(`/deployments/runs/${id}`)).data,
    enabled: Number.isFinite(id),
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 2000 : false),
  })
  const { data: apps } = useQuery<Application[]>({
    queryKey: ['applications-lite'],
    queryFn: async () => (await api.get('/applications')).data,
  })
  const appName = apps?.find((a) => a.id === run?.app_id)?.app_name

  useDocumentTitle(run ? `Çalıştırma #${run.id}` : 'Çalıştırma')

  // Tek bir başarısız adımı yeniden dener — tüm akışı değil (bkz. backend retry_step).
  const retryStepMutation = useMutation({
    mutationFn: async (stepId: number) =>
      (await api.post(`/deployments/runs/${id}/steps/${stepId}/retry`)).data as DeploymentRun,
    onSuccess: (updated) => {
      enqueueSnackbar('Adım yeniden tetiklendi', { variant: 'success' })
      qc.setQueryData(['deployment-run', id], updated)
      qc.invalidateQueries({ queryKey: ['deployment-runs'] })
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const [rerunConfirmOpen, setRerunConfirmOpen] = useState(false)
  const rerunMutation = useMutation({
    mutationFn: async () => (await api.post(`/deployments/runs/${id}/rerun`)).data as DeploymentRun,
    onSuccess: (newRun) => {
      enqueueSnackbar('Yeniden dağıtım başlatıldı', { variant: 'success' })
      qc.invalidateQueries({ queryKey: ['deployment-runs'] })
      setRerunConfirmOpen(false)
      navigate(`/deployments/runs/${newRun.id}`)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  // JUMBO'nun downstream tetiklemesini durdurur — Jenkins build'ini DURDURMAZ (bkz. backend cancel_run).
  const [cancelConfirmOpen, setCancelConfirmOpen] = useState(false)
  const cancelMutation = useMutation({
    mutationFn: async () => (await api.post(`/deployments/runs/${id}/cancel`)).data as DeploymentRun,
    onSuccess: (updated) => {
      enqueueSnackbar('Dağıtım iptal edildi', { variant: 'success' })
      qc.setQueryData(['deployment-run', id], updated)
      qc.invalidateQueries({ queryKey: ['deployment-runs'] })
      setCancelConfirmOpen(false)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const consoleLogMutation = useMutation({
    mutationFn: async ({ job, build }: { job: string; build: number }) =>
      (await api.get(`/jenkins/job/${job}/console-url`, { params: { build } })).data as { url: string },
    onSuccess: (data) => window.open(data.url, '_blank', 'noopener'),
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  if (isLoading || !run) {
    return (
      <Box>
        <PageHeader title="Çalıştırma" />
        <Typography color="text.secondary">Yükleniyor…</Typography>
      </Box>
    )
  }

  return (
    <Box>
      <PageHeader title={`Çalıştırma #${run.id}`} subtitle={run.flow_name_snapshot}
        actions={
          <Button component={RouterLink} to="/deployments" size="small" startIcon={<ArrowBackIcon />}>
            Dağıtım sayfasına dön
          </Button>
        } />

      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={4} sx={{ flexWrap: 'wrap', alignItems: 'center', rowGap: 2 }}>
          {appName && (
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Uygulama</Typography>
              <Typography variant="body2">{appName}</Typography>
            </Box>
          )}
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Durum</Typography>
            <StatusChip status={run.status} />
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Süre</Typography>
            <Typography variant="body2">{formatDuration(run.duration_seconds)}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Tetikleme</Typography>
            <Typography variant="body2">
              {TRIGGER_TYPE_LABELS[run.trigger_type] ?? run.trigger_type}
              {run.source_run_id != null && (
                <> — <RouterLink to={`/deployments/runs/${run.source_run_id}`}>#{run.source_run_id}</RouterLink></>
              )}
            </Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Tetikleyen</Typography>
            <Typography variant="body2">{run.triggered_by ?? '—'}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>Oluşturulma</Typography>
            <Typography variant="body2">{new Date(run.created_at).toLocaleString('tr-TR')}</Typography>
          </Box>
          <Box sx={{ flex: 1 }} />
          {isAdmin && (run.status === 'pending' || run.status === 'running') && (
            <Button variant="outlined" color="warning" startIcon={<CancelIcon />}
                   onClick={() => setCancelConfirmOpen(true)}>
              İptal Et
            </Button>
          )}
          {isAdmin && run.status === 'success' && (
            <Button variant="contained" startIcon={<ReplayIcon />} onClick={() => setRerunConfirmOpen(true)}>
              Yeniden Dağıt
            </Button>
          )}
        </Stack>
      </Paper>

      <Paper sx={{ p: 2 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>Adımlar</Typography>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Düğüm</TableCell>
              <TableCell>Job</TableCell>
              <TableCell>Parametreler</TableCell>
              <TableCell>Durum</TableCell>
              <TableCell>Süre</TableCell>
              <TableCell>Build</TableCell>
              <TableCell>Hata</TableCell>
              {isAdmin && <TableCell align="right">İşlem</TableCell>}
            </TableRow>
          </TableHead>
          <TableBody>
            {run.steps.map((s) => (
              <TableRow key={s.id}>
                <TableCell>{s.node_label}</TableCell>
                <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>{s.jenkins_job}</TableCell>
                <TableCell>
                  {Object.keys(s.params_snapshot).length === 0 ? '—' : Object.entries(s.params_snapshot).map(([k, v]) => (
                    <Typography key={k} variant="caption" sx={{ fontFamily: 'monospace', display: 'block' }}>
                      {k}={v}
                    </Typography>
                  ))}
                </TableCell>
                <TableCell><StatusChip status={s.status} /></TableCell>
                <TableCell>{formatDuration(s.duration_seconds)}</TableCell>
                <TableCell>
                  {s.jenkins_build_number == null ? '—' : (
                    <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
                      <Typography variant="body2">{s.jenkins_build_number}</Typography>
                      <Tooltip title="Jenkins konsol logunu yeni sekmede aç">
                        <IconButton size="small"
                                   onClick={() => consoleLogMutation.mutate({ job: s.jenkins_job, build: s.jenkins_build_number! })}>
                          <OpenInNewIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Stack>
                  )}
                </TableCell>
                <TableCell>
                  {s.error_message && (
                    <Tooltip title={s.error_message}>
                      <Typography variant="caption" color="error.main" noWrap sx={{ maxWidth: 220, display: 'block' }}>
                        {s.error_message}
                      </Typography>
                    </Tooltip>
                  )}
                </TableCell>
                {isAdmin && (
                  <TableCell align="right">
                    {s.status === 'failed' && (
                      <Tooltip title="Yalnız bu adımı yeniden tetikle (tüm akışı değil)">
                        <IconButton size="small" disabled={retryStepMutation.isPending}
                                   onClick={() => retryStepMutation.mutate(s.id)}>
                          <RestartAltIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    )}
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>

      <Dialog open={rerunConfirmOpen} onClose={() => setRerunConfirmOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Yeniden Dağıt</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 2 }}>
            "{run.flow_name_snapshot}" akışı, #{run.id} numaralı bu çalıştırmadaki AYNI parametrelerle
            yeni bir dağıtım olarak yeniden tetiklenecek:
          </Typography>
          <Stack spacing={1.5}>
            {run.steps.map((s) => (
              <Box key={s.id}>
                <Typography variant="caption" sx={{ fontWeight: 600 }}>{s.node_label} ({s.jenkins_job})</Typography>
                {Object.entries(s.params_snapshot).map(([k, v]) => (
                  <Typography key={k} variant="caption" sx={{ fontFamily: 'monospace', display: 'block', ml: 1 }}>
                    {k} = {v}
                  </Typography>
                ))}
              </Box>
            ))}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRerunConfirmOpen(false)}>Vazgeç</Button>
          <Button variant="contained" disabled={rerunMutation.isPending} onClick={() => rerunMutation.mutate()}>
            Onayla ve Dağıt
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={cancelConfirmOpen} onClose={() => setCancelConfirmOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Dağıtımı İptal Et</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            #{run.id} numaralı çalıştırma iptal edilecek — bekleyen/çalışan adımlar "İptal" olarak işaretlenir.
            Bu, yalnız JUMBO'nun sıradaki adımları tetiklemesini durdurur; hâlihazırda Jenkins'te çalışan bir
            build varsa ORADA durdurulmaz.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCancelConfirmOpen(false)}>Vazgeç</Button>
          <Button variant="contained" color="warning" disabled={cancelMutation.isPending}
                 onClick={() => cancelMutation.mutate()}>
            İptal Et
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
