import AddIcon from '@mui/icons-material/Add'
import CancelIcon from '@mui/icons-material/Cancel'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import UploadFileIcon from '@mui/icons-material/UploadFile'
import {
  Alert, Autocomplete, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  Paper, Skeleton, Table, TableBody, TableCell, TableHead, TableRow, TextField, Tooltip, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { Domain, IssuanceRequest } from '../api/types'
import PageHeader from '../components/PageHeader'
import QueryError from '../components/QueryError'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { usePageAccess } from '../hooks/usePageAccess'
import { issuanceStatusColor, issuanceStatusLabel, MONO_FONT } from '../theme'

const TRIGGER_LABEL: Record<string, string> = {
  scheduled_renewal: 'Zamanlanmış yenileme', manual: 'Elle', zero_touch: 'Zero-touch',
}
const OPEN_STATUSES = new Set(['pending_approval', 'approved', 'submitted', 'polling'])

export default function IssuanceRequests() {
  useDocumentTitle('Sertifika Talepleri')
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [csrDialogId, setCsrDialogId] = useState<number | null>(null)
  const [csrText, setCsrText] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [createDomain, setCreateDomain] = useState<Domain | null>(null)

  const { data: requests, isLoading, isError, error, refetch } = useQuery<IssuanceRequest[]>({
    queryKey: ['issuance-requests'],
    queryFn: async () => (await api.get('/issuance')).data,
  })

  const { data: domains } = useQuery<Domain[]>({
    queryKey: ['domains'],
    queryFn: async () => (await api.get('/domains')).data,
    enabled: createOpen,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['issuance-requests'] })
    queryClient.invalidateQueries({ queryKey: ['domains'] })
    queryClient.invalidateQueries({ queryKey: ['certificates'] })
    queryClient.invalidateQueries({ queryKey: ['proposals'] })
  }

  const decide = useMutation({
    mutationFn: async ({ id, action }: { id: number; action: 'approve' | 'reject' | 'cancel' }) =>
      (await api.post(`/issuance/${id}/${action}`)).data,
    onSuccess: (_d, v) => {
      const msg = v.action === 'approve' ? 'İstek onaylandı — CA çağrısı arka planda yapılacak'
        : v.action === 'reject' ? 'İstek reddedildi' : 'İstek iptal edildi'
      enqueueSnackbar(msg, { variant: v.action === 'approve' ? 'success' : 'info' })
      invalidate()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const submitCsr = useMutation({
    mutationFn: async ({ id, csr_pem }: { id: number; csr_pem: string }) =>
      (await api.post(`/issuance/${id}/csr`, { csr_pem })).data,
    onSuccess: () => {
      enqueueSnackbar('CSR eklendi', { variant: 'success' })
      setCsrDialogId(null)
      setCsrText('')
      invalidate()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const createRequest = useMutation({
    mutationFn: async (domain_id: number) =>
      (await api.post('/issuance', { domain_id })).data,
    onSuccess: () => {
      enqueueSnackbar('İstek oluşturuldu', { variant: 'success' })
      setCreateOpen(false)
      setCreateDomain(null)
      invalidate()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const rows = requests ?? []

  return (
    <Box>
      <PageHeader title="Sertifika Talepleri"
                  subtitle="CA'lardan otomatik sertifika alımı — özel anahtar JUMBO'ya hiç girmez" />

      <Alert severity="info" sx={{ mb: 2 }}>
        Bir isteği yalnız domain sahibi SY ekibinin üyesi (veya admin) onaylayabilir. Onay,
        CA'ya gerçek çağrıyı SENKRON YAPMAZ — arka planda birkaç saniye içinde işlenir. CSR
        (sertifika imzalama talebi) hedef sunucu/otomasyon tarafında üretilip buraya yalnız
        genel anahtar içeren metin olarak yüklenir; özel anahtar hiçbir zaman JUMBO'ya gitmez.
      </Alert>

      <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1 }}>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
          Yeni İstek
        </Button>
      </Box>

      <Paper variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Domain</TableCell>
              <TableCell>CA Profili</TableCell>
              <TableCell>Durum</TableCell>
              <TableCell>Tetikleyici</TableCell>
              <TableCell>SY Ekip</TableCell>
              <TableCell>CSR</TableCell>
              <TableCell align="right">Karar</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {isError && (
              <TableRow><TableCell colSpan={7}><QueryError error={error} onRetry={() => refetch()} /></TableCell></TableRow>
            )}
            {!isError && isLoading && [0, 1, 2].map((i) => (
              <TableRow key={i}><TableCell colSpan={7}><Skeleton height={32} /></TableCell></TableRow>
            ))}
            {!isError && !isLoading && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 6 }}>
                  <Typography color="text.secondary">Henüz bir otomatik alım isteği yok</Typography>
                </TableCell>
              </TableRow>
            )}
            {rows.map((r) => (
              <TableRow key={r.id} hover>
                <TableCell>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>{r.domain_name ?? `#${r.domain_id}`}</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ fontFamily: MONO_FONT }}>
                    {r.common_name}
                  </Typography>
                </TableCell>
                <TableCell>{r.profile_name ?? `#${r.profile_id}`}</TableCell>
                <TableCell>
                  <Chip size="small" color={issuanceStatusColor(r.status)} label={issuanceStatusLabel(r.status)} />
                  {r.zero_touch && <Chip size="small" variant="outlined" color="secondary" label="zero-touch" sx={{ ml: 0.5 }} />}
                  {r.status === 'failed' && r.last_error && (
                    <Tooltip title={r.last_error}>
                      <Typography variant="caption" color="error" sx={{ display: 'block', mt: 0.25 }}>
                        {r.last_error.slice(0, 60)}{r.last_error.length > 60 ? '…' : ''}
                      </Typography>
                    </Tooltip>
                  )}
                </TableCell>
                <TableCell>{TRIGGER_LABEL[r.trigger] ?? r.trigger}</TableCell>
                <TableCell>
                  {r.sy_team_name
                    ? <Chip size="small" label={r.sy_team_name} />
                    : <Chip size="small" variant="outlined" color="warning" label="sahipsiz" />}
                </TableCell>
                <TableCell>
                  {r.has_csr
                    ? <Chip size="small" color="success" variant="outlined" label="var" />
                    : (r.method === 'csr_sign' && OPEN_STATUSES.has(r.status) && (
                        <Button size="small" variant="outlined" startIcon={<UploadFileIcon />}
                                onClick={() => setCsrDialogId(r.id)}>
                          CSR Yükle
                        </Button>
                      ))}
                </TableCell>
                <TableCell align="right">
                  <Box sx={{ display: 'inline-flex', gap: 0.5, alignItems: 'center' }}>
                    {r.status === 'pending_approval' && (
                      r.can_decide ? (
                        <>
                          <Button size="small" variant="contained" color="success"
                                  startIcon={<CheckCircleIcon />} disabled={decide.isPending}
                                  onClick={() => decide.mutate({ id: r.id, action: 'approve' })}>
                            Onayla
                          </Button>
                          <Button size="small" variant="outlined" color="error"
                                  startIcon={<CancelIcon />} disabled={decide.isPending}
                                  onClick={() => decide.mutate({ id: r.id, action: 'reject' })}>
                            Reddet
                          </Button>
                        </>
                      ) : (
                        <Tooltip title="Bu isteği yalnız domain'in SY ekibi üyesi veya admin karara bağlayabilir">
                          <Chip size="small" variant="outlined" label="yetki yok" />
                        </Tooltip>
                      )
                    )}
                    {OPEN_STATUSES.has(r.status) && (
                      <Button size="small" variant="text" color="inherit" disabled={decide.isPending}
                              onClick={() => decide.mutate({ id: r.id, action: 'cancel' })}>
                        İptal
                      </Button>
                    )}
                  </Box>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>

      <Dialog open={csrDialogId !== null} onClose={() => setCsrDialogId(null)} maxWidth="sm" fullWidth>
        <DialogTitle>CSR Yükle</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Hedef sunucu/otomasyon tarafında üretilen CSR'ı (Certificate Signing Request) yapıştırın —
            yalnız genel anahtar + kimlik bilgisi içerir, özel anahtar İÇERMEMELİDİR.
          </Typography>
          <TextField fullWidth multiline minRows={8} placeholder="-----BEGIN CERTIFICATE REQUEST-----"
                     value={csrText} onChange={(e) => setCsrText(e.target.value)}
                     sx={{ '& textarea': { fontFamily: MONO_FONT, fontSize: 12 } }} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCsrDialogId(null)}>Vazgeç</Button>
          <Button variant="contained" disabled={!csrText.trim() || submitCsr.isPending}
                  onClick={() => csrDialogId !== null && submitCsr.mutate({ id: csrDialogId, csr_pem: csrText })}>
            Kaydet
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Yeni Otomatik Alım İsteği</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            CA profili domain ayarından (veya genel varsayılandan) otomatik seçilir — Ayarlar &gt;
            CA Profilleri'nde admin tarafından yapılandırılır.
          </Typography>
          <Autocomplete options={domains ?? []} getOptionLabel={(d) => d.domain}
                        value={createDomain} onChange={(_e, v) => setCreateDomain(v)}
                        renderInput={(params) => <TextField {...params} label="Domain" size="small" />} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Vazgeç</Button>
          <Button variant="contained" disabled={!createDomain || createRequest.isPending}
                  onClick={() => createDomain && createRequest.mutate(createDomain.id)}>
            Oluştur
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

// nav rozeti için bekleyen sayısını paylaşan hook
export function usePendingIssuanceCount() {
  const { issuance: canSee } = usePageAccess()
  const { data } = useQuery<IssuanceRequest[]>({
    queryKey: ['issuance-requests'],
    queryFn: async () => (await api.get('/issuance')).data,
    enabled: canSee,
    refetchInterval: 60_000,
  })
  return (data ?? []).filter((r) => r.status === 'pending_approval' && r.can_decide).length
}
