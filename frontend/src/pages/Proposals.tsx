import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CancelIcon from '@mui/icons-material/Cancel'
import CompareArrowsIcon from '@mui/icons-material/CompareArrows'
import {
  Alert, Box, Button, Chip, Paper, Skeleton, Table, TableBody, TableCell, TableHead,
  TableRow, Tooltip, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { TransferProposal } from '../api/types'
import PageHeader from '../components/PageHeader'
import ProposalReviewDrawer from '../components/ProposalReviewDrawer'
import QueryError from '../components/QueryError'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { usePageAccess } from '../hooks/usePageAccess'
import { mappingTypeLabel, MONO_FONT } from '../theme'

const VIA_LABEL: Record<string, string> = {
  import: 'İçe aktarma', manual: 'Elle', 'vault-sync': 'Vault senkron',
  'import-chain': 'Canlı zincir', 'live-check': 'Canlı doğrulama',
  attach: 'Elle eşleme', backfill: 'Geçiş',
}

export default function Proposals() {
  useDocumentTitle('Devir Önerileri')
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [reviewId, setReviewId] = useState<number | null>(null)

  const { data: proposals, isLoading, isError, error, refetch } = useQuery<TransferProposal[]>({
    queryKey: ['proposals', 'pending'],
    queryFn: async () => (await api.get('/proposals', { params: { status: 'pending' } })).data,
  })

  const reviewProposal = (proposals ?? []).find((p) => p.id === reviewId) ?? null
  // Aynı devrin (old→new cert) tüm bekleyen domain önerileri — çekmecede "Kapsam" için.
  const reviewGroup = reviewProposal
    ? (proposals ?? []).filter((p) => p.old_cert_id === reviewProposal.old_cert_id
        && p.new_cert_id === reviewProposal.new_cert_id)
    : []

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['proposals'] })
    queryClient.invalidateQueries({ queryKey: ['proposal-group'] })
    queryClient.invalidateQueries({ queryKey: ['domains'] })
    queryClient.invalidateQueries({ queryKey: ['certificates'] })
    queryClient.invalidateQueries({ queryKey: ['certificate'] })
  }

  const decide = useMutation({
    mutationFn: async ({ id, action }: { id: number; action: 'approve' | 'reject' }) =>
      (await api.post(`/proposals/${id}/${action}`)).data,
    onSuccess: (_d, v) => {
      enqueueSnackbar(v.action === 'approve' ? 'Devir onaylandı ve uygulandı' : 'Öneri reddedildi',
                      { variant: v.action === 'approve' ? 'success' : 'info' })
      setReviewId(null)
      invalidate()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const rows = proposals ?? []

  return (
    <Box>
      <PageHeader title="Devir Önerileri"
                  subtitle="Sertifika rotasyonlarının SY ekibi onay hattı — JUMBO yalnız önerir, devir onayla uygulanır" />

      <Alert severity="info" sx={{ mb: 2 }}>
        Bir devir önerisini yalnız domain sahibi SY ekibinin üyesi (veya admin) onaylayabilir.
        Onayladığınızda eşleme yeni sertifikaya taşınır ve eski kayıt pasife alınır; reddederseniz
        hiçbir değişiklik olmaz.
      </Alert>

      <Paper variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Devir (Eski → Yeni)</TableCell>
              <TableCell>Domain / Hedef</TableCell>
              <TableCell>Tip</TableCell>
              <TableCell>SY Ekip</TableCell>
              <TableCell>Kaynak</TableCell>
              <TableCell>Kanıt</TableCell>
              <TableCell align="right">Karar</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {isError && (
              <TableRow>
                <TableCell colSpan={7}>
                  <QueryError error={error} onRetry={() => refetch()} />
                </TableCell>
              </TableRow>
            )}
            {!isError && isLoading && [0, 1, 2].map((i) => (
              <TableRow key={i}><TableCell colSpan={7}><Skeleton height={32} /></TableCell></TableRow>
            ))}
            {!isError && !isLoading && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 6 }}>
                  <Typography color="text.secondary">Onay bekleyen devir önerisi yok</Typography>
                </TableCell>
              </TableRow>
            )}
            {rows.map((p) => (
              <TableRow key={p.id} hover>
                <TableCell>
                  <Tooltip title="Eski ve yeni sertifikayı karşılaştır">
                    <Box onClick={() => setReviewId(p.id)}
                         sx={{
                           display: 'flex', alignItems: 'center', gap: 0.75, flexWrap: 'wrap',
                           cursor: 'pointer', borderRadius: 1, mx: -0.5, px: 0.5, py: 0.25,
                           '&:hover': { bgcolor: 'action.hover' },
                         }}>
                      <Chip size="small" label="ESKİ" sx={{ fontWeight: 700 }} />
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>{p.old_cert_name}</Typography>
                      <Typography color="info.main">→</Typography>
                      <Chip size="small" color="info" label="YENİ" sx={{ fontWeight: 700 }} />
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>{p.new_cert_name}</Typography>
                      {p.signal && (
                        <Chip size="small" variant="outlined"
                              label={p.signal === 'ski' ? 'aynı anahtar' : 'aynı CN+CA'} />
                      )}
                      {p.kind === 'trusted_add' && (
                        <Chip size="small" color="secondary" variant="outlined"
                              label="trust store'a ekle — eski kalır" />
                      )}
                      <CompareArrowsIcon fontSize="small" sx={{ color: 'info.main', ml: 0.25 }} />
                    </Box>
                  </Tooltip>
                </TableCell>
                <TableCell>{p.kind === 'trusted_add'
                  ? `${p.app_name ?? 'uygulama'} (trust store)`
                  : (p.domain_name ?? (p.app_dependency_id ? 'mTLS bağımlılığı' : '—'))}</TableCell>
                <TableCell>
                  {p.kind === 'trusted_add'
                    ? <Chip size="small" color="secondary" variant="outlined" label="trusted (ekle)" />
                    : (p.mapping_type && <Chip size="small" variant="outlined" label={mappingTypeLabel(p.mapping_type)} />)}
                </TableCell>
                <TableCell>
                  {p.sy_team_name
                    ? <Chip size="small" label={p.sy_team_name} />
                    : <Tooltip title="Domain'in SY sahibi yok — yalnız admin onaylar">
                        <Chip size="small" variant="outlined" color="warning" label="sahipsiz" />
                      </Tooltip>}
                </TableCell>
                <TableCell>
                  <Typography variant="caption" sx={{ fontFamily: MONO_FONT }}>
                    {VIA_LABEL[p.via ?? ''] ?? p.via}
                  </Typography>
                </TableCell>
                <TableCell>
                  {p.live_seen && (
                    <Tooltip title="Yeni sertifika sunucuda canlı görüldü — devri onaylamak güvenli">
                      <Chip size="small" color="success" variant="outlined" icon={<CheckCircleIcon />}
                            label="canlıda" />
                    </Tooltip>
                  )}
                </TableCell>
                <TableCell align="right">
                  <Box sx={{ display: 'inline-flex', gap: 0.5, alignItems: 'center' }}>
                    <Button size="small" variant="outlined" color="inherit"
                            startIcon={<CompareArrowsIcon />} onClick={() => setReviewId(p.id)}>
                      İncele
                    </Button>
                    {p.can_decide ? (
                      <>
                        <Button size="small" variant="contained" color="success"
                                startIcon={<CheckCircleIcon />} disabled={decide.isPending}
                                onClick={() => decide.mutate({ id: p.id, action: 'approve' })}>
                          Onayla
                        </Button>
                        <Button size="small" variant="outlined" color="error"
                                startIcon={<CancelIcon />} disabled={decide.isPending}
                                onClick={() => decide.mutate({ id: p.id, action: 'reject' })}>
                          Reddet
                        </Button>
                      </>
                    ) : (
                      <Tooltip title="Bu öneriyi yalnız domain'in SY ekibi üyesi veya admin karara bağlayabilir">
                        <Chip size="small" variant="outlined" label="yetki yok" />
                      </Tooltip>
                    )}
                  </Box>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>

      <ProposalReviewDrawer
        proposal={reviewProposal}
        group={reviewGroup}
        onClose={() => setReviewId(null)}
        deciding={decide.isPending}
        onDecide={(id, action) => decide.mutate({ id, action })}
      />
    </Box>
  )
}

// nav rozeti için bekleyen sayısını paylaşan hook
export function usePendingProposalCount() {
  const { proposals: canSee } = usePageAccess()
  const { data } = useQuery<TransferProposal[]>({
    queryKey: ['proposals', 'pending'],
    queryFn: async () => (await api.get('/proposals', { params: { status: 'pending' } })).data,
    enabled: canSee,
    refetchInterval: 60_000,
  })
  return (data ?? []).filter((p) => p.can_decide).length
}
