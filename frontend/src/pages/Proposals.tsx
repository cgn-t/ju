import CancelIcon from '@mui/icons-material/Cancel'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CompareArrowsIcon from '@mui/icons-material/CompareArrows'
import FilterAltOffIcon from '@mui/icons-material/FilterAltOff'
import SearchIcon from '@mui/icons-material/Search'
import {
  Alert, Autocomplete, Box, Button, Chip, FormControlLabel, InputAdornment, LinearProgress, Link,
  MenuItem, Paper, Skeleton, Stack, Switch, Tab, Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, Tabs, TextField, Tooltip, Typography,
} from '@mui/material'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { DomainOption, ProposalPage, Team, TransferProposal } from '../api/types'
import ListPagination from '../components/ListPagination'
import PageHeader from '../components/PageHeader'
import ProposalReviewDrawer from '../components/ProposalReviewDrawer'
import QueryError from '../components/QueryError'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { usePageAccess } from '../hooks/usePageAccess'
import { useDebounced, usePaging } from '../hooks/usePaging'
import { useUrlId, useUrlParams, useUrlPatch } from '../hooks/useUrlState'
import { mappingTypeLabel, MONO_FONT } from '../theme'
import { proposerLine, VIA_LABEL, viaLabel } from '../utils/proposalLabels'

const fmtDay = (v?: string | null) => (v ? new Date(v).toLocaleDateString('tr-TR') : '—')

// Durum sekmeleri (sıra = ekrandaki sıra). "approved" ara durumdur; yalnız varsa görünür.
const STATUS_TABS = [
  { value: 'pending', label: 'Bekleyen' },
  { value: 'applied', label: 'Uygulanan' },
  { value: 'approved', label: 'Onaylandı (uygulanmadı)' },
  { value: 'rejected', label: 'Reddedilen' },
  { value: 'cancelled', label: 'İptal edilen' },
  { value: 'all', label: 'Tümü' },
] as const
type StatusTab = (typeof STATUS_TABS)[number]['value']

const STATUS_META: Record<TransferProposal['status'], { label: string; color: 'default' | 'success' | 'error' | 'warning' | 'info' }> = {
  pending: { label: 'Bekliyor', color: 'warning' },
  approved: { label: 'Onaylandı', color: 'info' },
  applied: { label: 'Uygulandı', color: 'success' },
  rejected: { label: 'Reddedildi', color: 'error' },
  cancelled: { label: 'İptal edildi', color: 'default' },
}

export const KIND_LABEL: Record<string, string> = {
  transfer: 'Sertifika değişimi (eski → yeni)',
  date_fix: 'Tarih güncelleme (TARİH)',
  server_add: 'Sunucuya eklenen (EKLE)',
  server_remove: 'Sunucudan kalkan (KALDIR)',
  trusted_add: "Trust store'a ekle",
}

const SORTS = [
  { value: 'new', label: 'Tarih: yeniden eskiye', sort: 'created_at', dir: 'desc' },
  { value: 'old', label: 'Tarih: eskiden yeniye', sort: 'created_at', dir: 'asc' },
  { value: 'domain', label: 'Domain: A → Z', sort: 'domain', dir: 'asc' },
] as const

export default function Proposals() {
  useDocumentTitle('Değişiklik Talepleri')
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [reviewId, setReviewId] = useUrlId('review')
  const params = useUrlParams()
  const patch = useUrlPatch()

  // Tüm filtreler adreste: "Onaya git" (domain penceresi) ?domain=<id> ile buraya filtreli gelir,
  // bağlantı paylaşılınca aynı görünüm açılır.
  const status = (STATUS_TABS.some((t) => t.value === params.get('status')) ? params.get('status') : 'pending') as StatusTab
  const domainId = /^\d+$/.test(params.get('domain') ?? '') ? Number(params.get('domain')) : null
  const kind = KIND_LABEL[params.get('kind') ?? ''] ? params.get('kind')! : ''
  const syTeam = /^\d+$/.test(params.get('sy') ?? '') ? Number(params.get('sy')) : null
  const via = VIA_LABEL[params.get('via') ?? ''] ? params.get('via')! : ''
  const liveOnly = params.get('live') === '1'
  const mineOnly = params.get('karar') === '1'
  const sortKey = SORTS.find((x) => x.value === params.get('sirala'))?.value ?? 'new'
  const sort = SORTS.find((x) => x.value === sortKey)!
  const urlQ = params.get('q') ?? ''
  const [qInput, setQInput] = useState(urlQ)
  useEffect(() => setQInput(urlQ), [urlQ])
  const q = useDebounced(qInput)
  useEffect(() => { if (q !== urlQ) patch({ q: q || null }) }, [q])  // eslint-disable-line react-hooks/exhaustive-deps

  const filterParams = JSON.stringify({
    status, domain_id: domainId ?? undefined, kind: kind || undefined, sy_team_id: syTeam ?? undefined,
    via: via || undefined, live_seen: liveOnly || undefined, decidable: mineOnly || undefined,
    q: urlQ.trim() || undefined, sort: sort.sort, dir: sort.dir,
  })
  const paging = usePaging(filterParams, 25)

  const { data, isLoading, isFetching, isError, error, refetch } = useQuery<ProposalPage>({
    queryKey: ['proposals', 'page', filterParams, paging.page, paging.size],
    queryFn: async () => (await api.get('/proposals/page', {
      params: { ...JSON.parse(filterParams), page: paging.page, size: paging.size },
    })).data,
    placeholderData: keepPreviousData,
  })
  const items = data?.items ?? []

  const { data: teams } = useQuery<Team[]>({
    queryKey: ['teams'],
    queryFn: async () => (await api.get('/teams')).data,
  })
  const syTeams = (teams ?? []).filter((t) => t.type === 'SY')
  const { data: domainOptions } = useQuery<DomainOption[]>({
    queryKey: ['domain-options'],
    queryFn: async () => (await api.get('/domains/options')).data,
    staleTime: 60_000,
  })
  const selectedDomain = domainId !== null
    ? (domainOptions ?? []).find((d) => d.id === domainId)
      ?? { id: domainId, domain: data?.domain_name ?? `#${domainId}` }
    : null

  // İncelenen talep sayfada olmayabilir (doğrudan bağlantı) → tekil uçtan al
  const onPage = items.find((p) => p.id === reviewId) ?? null
  const { data: fetchedReview } = useQuery<TransferProposal>({
    queryKey: ['proposal', reviewId],
    queryFn: async () => (await api.get(`/proposals/${reviewId}`)).data,
    enabled: reviewId !== null && !onPage && !isLoading,
  })
  const reviewProposal = onPage ?? (fetchedReview?.id === reviewId ? fetchedReview : null)
  // Aynı devrin (old→new cert) sayfadaki bekleyen domain talepleri — çekmece tam listeyi kendisi çeker.
  const reviewGroup = reviewProposal
    ? items.filter((p) => p.old_cert_id === reviewProposal.old_cert_id
        && p.new_cert_id === reviewProposal.new_cert_id && p.kind === reviewProposal.kind)
    : []

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['proposals'] })
    queryClient.invalidateQueries({ queryKey: ['proposal'] })
    queryClient.invalidateQueries({ queryKey: ['proposal-group'] })
    queryClient.invalidateQueries({ queryKey: ['domains'] })
    queryClient.invalidateQueries({ queryKey: ['domain'] })
    queryClient.invalidateQueries({ queryKey: ['certificates'] })
    queryClient.invalidateQueries({ queryKey: ['certificate'] })
  }

  const decide = useMutation({
    mutationFn: async ({ id, action }: { id: number; action: 'approve' | 'reject' }) =>
      (await api.post(`/proposals/${id}/${action}`)).data,
    onSuccess: (_d, v) => {
      enqueueSnackbar(v.action === 'approve' ? 'Değişiklik onaylandı ve uygulandı' : 'Talep reddedildi',
                      { variant: v.action === 'approve' ? 'success' : 'info' })
      setReviewId(null)
      invalidate()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  // Etkin filtre çipleri (durum sekmesi hariç) — tek tıkla kaldırılır
  const chips: { key: string; label: string; clear: Record<string, null> }[] = [
    ...(domainId !== null ? [{ key: 'domain', label: `Domain: ${selectedDomain?.domain}`, clear: { domain: null } }] : []),
    ...(kind ? [{ key: 'kind', label: `Tür: ${KIND_LABEL[kind]}`, clear: { kind: null } }] : []),
    ...(syTeam !== null ? [{ key: 'sy', label: `SY: ${syTeams.find((t) => t.id === syTeam)?.name ?? `#${syTeam}`}`, clear: { sy: null } }] : []),
    ...(via ? [{ key: 'via', label: `Kaynak: ${VIA_LABEL[via]}`, clear: { via: null } }] : []),
    ...(liveOnly ? [{ key: 'live', label: 'Canlıda görüldü', clear: { live: null } }] : []),
    ...(mineOnly ? [{ key: 'karar', label: 'Karar verebileceklerim', clear: { karar: null } }] : []),
    ...(urlQ ? [{ key: 'q', label: `Arama: "${urlQ}"`, clear: { q: null } }] : []),
  ]
  const clearAll = () => patch({ domain: null, kind: null, sy: null, via: null, live: null, karar: null, q: null })
  const counts = data?.counts ?? {}
  const kindCounts = data?.facets?.kind ?? {}

  return (
    <Box>
      <PageHeader title="Değişiklik Talepleri"
                  subtitle="Sertifika rotasyonlarının SY ekibi onay hattı — JUMBO yalnız önerir, değişiklik onayla uygulanır" />

      <Alert severity="info" sx={{ mb: 2 }}>
        Bir değişiklik talebini yalnız domain sahibi SY ekibinin üyesi (veya admin) onaylayabilir.
        Onayladığınızda bağlantı yeni sertifikaya taşınır ve eski kayıt pasife alınır; reddederseniz
        hiçbir değişiklik olmaz.
      </Alert>

      <Paper variant="outlined" sx={{ mb: 2, overflow: 'hidden' }}>
        <Tabs value={status} onChange={(_, v) => patch({ status: v === 'pending' ? null : v })}
              variant="scrollable" scrollButtons="auto"
              sx={{ px: 1, borderBottom: 1, borderColor: 'divider', minHeight: 44,
                    '& .MuiTab-root': { minHeight: 44, textTransform: 'none', fontWeight: 600 } }}>
          {STATUS_TABS.filter((t) => t.value !== 'approved' || (counts.approved ?? 0) > 0 || status === 'approved')
            .map((t) => (
              <Tab key={t.value} value={t.value} label={
                <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
                  {t.label}
                  <Chip size="small" label={counts[t.value] ?? 0}
                        color={t.value === 'pending' && (counts.pending ?? 0) > 0 ? 'warning' : 'default'}
                        sx={{ height: 20, fontSize: 12, '& .MuiChip-label': { px: 0.75 } }} />
                </Box>
              } />
            ))}
        </Tabs>
        <Box sx={{ p: 1.5, display: 'flex', gap: 1.5, flexWrap: 'wrap', alignItems: 'center' }}>
          <TextField size="small" placeholder="Ara: domain, sertifika, uygulama" value={qInput}
                     onChange={(e) => setQInput(e.target.value)} sx={{ width: { xs: '100%', sm: 320 } }}
                     slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }} />
          <Autocomplete size="small" sx={{ width: { xs: '100%', sm: 280 } }}
                        options={domainOptions ?? []} value={selectedDomain}
                        getOptionLabel={(d) => d.domain} isOptionEqualToValue={(a, b) => a.id === b.id}
                        onChange={(_, d) => patch({ domain: d ? String(d.id) : null })}
                        renderInput={(p) => <TextField {...p} label="Domain" />} />
          <TextField select size="small" label="Tür" value={kind} sx={{ width: 230 }}
                     onChange={(e) => patch({ kind: e.target.value || null })}>
            <MenuItem value=""><em>Tümü</em></MenuItem>
            {Object.entries(KIND_LABEL).map(([k, label]) => (
              <MenuItem key={k} value={k} sx={{ display: 'flex', gap: 1 }}>
                <Box sx={{ flexGrow: 1 }}>{label}</Box>
                <Typography variant="caption" color="text.secondary">{kindCounts[k] ?? 0}</Typography>
              </MenuItem>
            ))}
          </TextField>
          <TextField select size="small" label="SY Ekip" value={syTeam !== null ? String(syTeam) : ''} sx={{ width: 190 }}
                     onChange={(e) => patch({ sy: e.target.value || null })}>
            <MenuItem value=""><em>Tümü</em></MenuItem>
            {syTeams.map((t) => <MenuItem key={t.id} value={String(t.id)}>{t.name}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Kaynak" value={via} sx={{ width: 170 }}
                     onChange={(e) => patch({ via: e.target.value || null })}>
            <MenuItem value=""><em>Tümü</em></MenuItem>
            {Object.entries(VIA_LABEL).map(([k, label]) => <MenuItem key={k} value={k}>{label}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Sıralama" value={sortKey} sx={{ width: 200 }}
                     onChange={(e) => patch({ sirala: e.target.value === 'new' ? null : e.target.value })}>
            {SORTS.map((x) => <MenuItem key={x.value} value={x.value}>{x.label}</MenuItem>)}
          </TextField>
          <FormControlLabel sx={{ ml: 0 }}
                            control={<Switch size="small" checked={liveOnly} onChange={(e) => patch({ live: e.target.checked ? '1' : null })} />}
                            label={<Typography variant="body2">Canlıda görüldü</Typography>} />
          <FormControlLabel sx={{ ml: 0 }}
                            control={<Switch size="small" checked={mineOnly} onChange={(e) => patch({ karar: e.target.checked ? '1' : null })} />}
                            label={<Typography variant="body2">Yalnız karar verebileceklerim</Typography>} />
        </Box>
        {chips.length > 0 && (
          <Stack direction="row" spacing={1} useFlexGap
                 sx={{ px: 1.5, pb: 1.5, flexWrap: 'wrap', alignItems: 'center' }}>
            {chips.map((c) => (
              <Chip key={c.key} size="small" color="primary" variant="outlined" label={c.label}
                    onDelete={() => patch(c.clear)} />
            ))}
            <Button size="small" startIcon={<FilterAltOffIcon fontSize="small" />} onClick={clearAll}>
              Filtreleri temizle
            </Button>
          </Stack>
        )}
      </Paper>

      <LinearProgress sx={{ mb: 0.5, height: 2, visibility: isFetching && !isLoading ? 'visible' : 'hidden' }} />
      <Paper variant="outlined">
        <TableContainer sx={{ overflowX: 'auto' }}>
        <Table size="small" sx={{ minWidth: 980 }}>
          <TableHead>
            <TableRow>
              <TableCell>Değişiklik (Eski → Yeni)</TableCell>
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
            {!isError && !isLoading && items.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 6 }}>
                  <Typography color="text.secondary">
                    {chips.length
                      ? 'Bu filtrelerle eşleşen değişiklik talebi yok'
                      : status === 'pending' ? 'Onay bekleyen değişiklik talebi yok' : 'Bu durumda değişiklik talebi yok'}
                  </Typography>
                  {chips.length > 0 && <Button size="small" onClick={clearAll} sx={{ mt: 1 }}>Filtreleri temizle</Button>}
                </TableCell>
              </TableRow>
            )}
            {items.map((p) => (
              <TableRow key={p.id} hover>
                <TableCell>
                  <Tooltip title={p.kind === 'server_add' || p.kind === 'server_remove' || p.kind === 'date_fix'
                    ? 'Talebi incele' : 'Eski ve yeni sertifikayı karşılaştır'}>
                    <Box onClick={() => setReviewId(p.id)}
                         sx={{
                           display: 'flex', alignItems: 'center', gap: 0.75, flexWrap: 'wrap',
                           cursor: 'pointer', borderRadius: 1, mx: -0.5, px: 0.5, py: 0.25,
                           '&:hover': { bgcolor: 'action.hover' },
                         }}>
                      {p.kind === 'date_fix' ? (
                        <>
                          <Chip size="small" sx={{ fontWeight: 700 }} color="info" label="TARİH" />
                          <Typography variant="body2" sx={{ fontWeight: 600 }}>{p.new_cert_name}</Typography>
                          <Typography variant="caption" color="text.secondary">
                            bitiş {fmtDay(p.record_valid_to)} → {fmtDay(p.cert_valid_to)}
                          </Typography>
                        </>
                      ) : p.kind === 'server_add' || p.kind === 'server_remove' ? (
                        <>
                          <Chip size="small" sx={{ fontWeight: 700 }}
                                color={p.kind === 'server_add' ? 'success' : 'warning'}
                                label={p.kind === 'server_add' ? 'EKLE' : 'KALDIR'} />
                          <Typography variant="body2" sx={{ fontWeight: 600 }}>{p.new_cert_name}</Typography>
                        </>
                      ) : (
                        <>
                          <Chip size="small" label="ESKİ" sx={{ fontWeight: 700 }} />
                          <Typography variant="body2" sx={{ fontWeight: 600 }}>{p.old_cert_name}</Typography>
                          <Typography color="info.main">→</Typography>
                          <Chip size="small" color="info" label="YENİ" sx={{ fontWeight: 700 }} />
                          <Typography variant="body2" sx={{ fontWeight: 600 }}>{p.new_cert_name}</Typography>
                        </>
                      )}
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
                  : p.domain_id && p.domain_name
                    ? (
                      <Tooltip title="Yalnız bu domainin taleplerini göster">
                        <Link component="button" underline="hover" color="inherit"
                              onClick={() => patch({ domain: String(p.domain_id) })}
                              sx={{ textAlign: 'left', fontWeight: 500 }}>
                          {p.domain_name}
                        </Link>
                      </Tooltip>
                    )
                    : (p.domain_name ?? (p.app_dependency_id ? 'Trusted bağlantı' : '—'))}</TableCell>
                <TableCell>
                  {p.kind === 'trusted_add'
                    ? <Chip size="small" color="secondary" variant="outlined" label="trusted (ekle)" />
                    : p.kind === 'date_fix'
                    ? <Chip size="small" color="info" variant="outlined" label="tarih güncelleme" />
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
                  <Typography variant="caption" sx={{ fontFamily: MONO_FONT, display: 'block' }}>
                    {viaLabel(p.via, p.created_by)}
                  </Typography>
                  <Typography variant="caption" color="text.secondary"
                              sx={{ display: 'block', whiteSpace: 'nowrap' }}>
                    {proposerLine(p.created_by, p.created_at, p.created_by_name)}
                  </Typography>
                </TableCell>
                <TableCell>
                  {p.live_seen && (
                    <Tooltip title="Yeni sertifika sunucuda canlı görüldü — değişikliği onaylamak güvenli">
                      <Chip size="small" color="success" variant="outlined" icon={<CheckCircleIcon />}
                            label="canlıda" />
                    </Tooltip>
                  )}
                </TableCell>
                <TableCell align="right" sx={{ width: 230 }}>
                  <Box sx={{ display: 'inline-flex', gap: 0.5, alignItems: 'center', flexWrap: 'wrap',
                             justifyContent: 'flex-end', maxWidth: 230 }}>
                    <Button size="small" variant="outlined" color="inherit"
                            startIcon={<CompareArrowsIcon />} onClick={() => setReviewId(p.id)}>
                      İncele
                    </Button>
                    {p.status !== 'pending' ? (
                      <Tooltip title={p.decided_by ? `${p.decided_by} · ${fmtDay(p.decided_at)}` : ''}>
                        <Chip size="small" variant="outlined" color={STATUS_META[p.status].color}
                              label={STATUS_META[p.status].label} />
                      </Tooltip>
                    ) : p.can_decide ? (
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
                      <Tooltip title="Bu talebi yalnız domain'in SY ekibi üyesi veya admin karara bağlayabilir">
                        <Chip size="small" variant="outlined" label="yetki yok" />
                      </Tooltip>
                    )}
                  </Box>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        </TableContainer>
        {!isError && !isLoading && (
          <ListPagination total={data?.total ?? 0} page={paging.page} size={paging.size}
                          onPage={paging.setPage} onSize={paging.setSize} unit="talep" />
        )}
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

// nav rozeti: bu kullanıcının karar verebileceği bekleyen talep sayısı (hafif sayaç ucu)
export function usePendingProposalCount() {
  const { proposals: canSee } = usePageAccess()
  const { data } = useQuery<{ pending: number; decidable: number }>({
    queryKey: ['proposals', 'counts'],
    queryFn: async () => (await api.get('/proposals/counts')).data,
    enabled: canSee,
    refetchInterval: 60_000,
  })
  return data?.decidable ?? 0
}
