import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch'
import {
  Alert, Autocomplete, Box, Button, Chip, CircularProgress, Grid, IconButton, Paper, Stack,
  Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, apiErrorMessage } from '../api/client'
import PageHeader from '../components/PageHeader'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

type Build = { number: number; result: string | null; building: boolean; timestamp: number; duration: number }

function BuildStatus({ b }: { b: Build }) {
  if (b.building) {
    return <Chip size="small" color="info" icon={<CircularProgress size={12} color="inherit" />} label="Çalışıyor" />
  }
  const map: Record<string, { label: string; color: 'success' | 'error' | 'default' | 'warning' }> = {
    SUCCESS: { label: 'Başarılı', color: 'success' },
    FAILURE: { label: 'Başarısız', color: 'error' },
    UNSTABLE: { label: 'Kararsız', color: 'warning' },
    ABORTED: { label: 'İptal', color: 'default' },
  }
  const m = map[b.result ?? ''] ?? { label: b.result ?? '—', color: 'default' as const }
  return <Chip size="small" color={m.color} label={m.label} variant="outlined" />
}

export default function Deployments() {
  useDocumentTitle('Dağıtım')
  const { enqueueSnackbar } = useSnackbar()
  const qc = useQueryClient()

  const cfg = useQuery<{ enabled?: boolean; netscaler_job?: string }>({
    queryKey: ['settings', 'jenkins'],
    queryFn: async () => (await api.get('/settings/jenkins')).data,
  })
  const enabled = !!cfg.data?.enabled

  const jobs = useQuery<{ jobs: string[] }>({
    queryKey: ['jenkins-jobs'],
    queryFn: async () => (await api.get('/jenkins/jobs')).data,
    enabled,
  })

  const [job, setJob] = useState('')
  useEffect(() => {
    if (!job && cfg.data?.netscaler_job) setJob(cfg.data.netscaler_job)
  }, [cfg.data, job])

  const [rows, setRows] = useState<{ key: string; value: string }[]>([
    { key: 'CERTKEY', value: 'demo_ck' },
    { key: 'VAULT_PATH', value: 'secret/data/certs/demo' },
  ])
  const setRow = (i: number, patch: Partial<{ key: string; value: string }>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  const builds = useQuery<{ builds: Build[] }>({
    queryKey: ['jenkins-builds', job],
    queryFn: async () => (await api.get(`/jenkins/job/${encodeURIComponent(job)}/builds`)).data,
    enabled: enabled && !!job,
    refetchInterval: (q) => (q.state.data?.builds?.some((b) => b.building) ? 2000 : 6000),
  })

  const trigger = useMutation({
    mutationFn: async () => {
      const params = Object.fromEntries(rows.filter((r) => r.key.trim()).map((r) => [r.key.trim(), r.value]))
      return (await api.post('/jenkins/trigger', { job: job.trim(), params })).data
    },
    onSuccess: (d) => {
      enqueueSnackbar(d.message, { variant: d.success ? 'success' : 'warning' })
      setTimeout(() => qc.invalidateQueries({ queryKey: ['jenkins-builds', job] }), 1500)
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  if (cfg.data && !enabled) {
    return (
      <Box>
        <PageHeader title="Dağıtım" subtitle="Jenkins ile sertifika dağıtımını tetikle" />
        <Alert severity="info">
          Jenkins entegrasyonu kapalı. <Link to="/settings">Ayarlar → Jenkins</Link> bölümünden adres ve
          kimlik bilgilerini girip etkinleştirin.
        </Alert>
      </Box>
    )
  }

  return (
    <Box>
      <PageHeader title="Dağıtım"
        subtitle="Jenkins job'unu tetikleyerek sertifikayı dağıt (NetScaler vb.). Anahtar Vault→Jenkins→NITRO yolunu izler; JUMBO'ya girmez." />
      <Grid container spacing={2}>
        {/* Yeni Dağıtım */}
        <Grid size={{ xs: 12, md: 5 }}>
          <Paper sx={{ p: 2.5 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 0.5 }}>Yeni Dağıtım</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Aynı job'u farklı domainler için farklı <code>CERTKEY</code>/<code>VAULT_PATH</code> ile
              tetikleyebilirsiniz.
            </Typography>
            <Stack spacing={2}>
              <Autocomplete
                freeSolo options={jobs.data?.jobs ?? []} value={job}
                onInputChange={(_, v) => setJob(v)}
                renderInput={(p) => <TextField {...p} size="small" label="Job" placeholder="netscaler-deploy" />}
              />
              <Stack spacing={1}>
                {rows.map((row, i) => (
                  <Stack key={i} direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                    <TextField size="small" label="Parametre" value={row.key}
                               onChange={(e) => setRow(i, { key: e.target.value })} sx={{ flex: 1 }} />
                    <TextField size="small" label="Değer" value={row.value}
                               onChange={(e) => setRow(i, { value: e.target.value })} sx={{ flex: 2 }} />
                    <IconButton size="small" aria-label="Sil"
                                onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Stack>
                ))}
                <Box>
                  <Button size="small" startIcon={<AddIcon />}
                          onClick={() => setRows((rs) => [...rs, { key: '', value: '' }])}>Parametre ekle</Button>
                </Box>
              </Stack>
              <Box>
                <Button variant="contained" startIcon={<RocketLaunchIcon />}
                        disabled={!job.trim() || trigger.isPending} onClick={() => trigger.mutate()}>
                  {trigger.isPending ? 'Tetikleniyor…' : 'Dağıt'}
                </Button>
              </Box>
            </Stack>
          </Paper>
        </Grid>

        {/* Son Dağıtımlar */}
        <Grid size={{ xs: 12, md: 7 }}>
          <Paper sx={{ p: 2.5 }}>
            <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Son Dağıtımlar</Typography>
              <Typography variant="caption" color="text.secondary">
                {job ? `job: ${job}` : 'job seçilmedi'} · canlı
              </Typography>
            </Stack>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>#</TableCell>
                  <TableCell>Durum</TableCell>
                  <TableCell>Zaman</TableCell>
                  <TableCell align="right">Süre</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(builds.data?.builds ?? []).map((b) => (
                  <TableRow key={b.number}>
                    <TableCell sx={{ fontWeight: 600 }}>#{b.number}</TableCell>
                    <TableCell><BuildStatus b={b} /></TableCell>
                    <TableCell>{b.timestamp ? new Date(b.timestamp).toLocaleString('tr-TR') : '—'}</TableCell>
                    <TableCell align="right">{b.duration ? `${Math.round(b.duration / 1000)} sn` : '—'}</TableCell>
                  </TableRow>
                ))}
                {enabled && job && (builds.data?.builds?.length ?? 0) === 0 && (
                  <TableRow><TableCell colSpan={4} sx={{ color: 'text.secondary' }}>Henüz dağıtım yok.</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  )
}
