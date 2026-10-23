import CheckIcon from '@mui/icons-material/Check'
import FilterAltOffIcon from '@mui/icons-material/FilterAltOff'
import HowToRegOutlinedIcon from '@mui/icons-material/HowToRegOutlined'
import LockOutlinedIcon from '@mui/icons-material/LockOutlined'
import SensorsIcon from '@mui/icons-material/Sensors'
import SortIcon from '@mui/icons-material/Sort'
import {
  Autocomplete, Box, Button, InputAdornment, Link, MenuItem, Skeleton, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, TextField, Tooltip, Typography,
} from '@mui/material'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useState, type ReactNode } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { DomainOption, ProposalPage, Team, TransferProposal } from '../api/types'
import { StatusPill, type Tone } from '../components/DetailCards'
import ListPagination from '../components/ListPagination'
import { ActiveFilters, EmptyState, ListCard, SearchBox, StatusTabs, ToggleChip } from '../components/ListKit'
import PageHeader from '../components/PageHeader'
import ProposalReviewDrawer from '../components/ProposalReviewDrawer'
import QueryError from '../components/QueryError'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { usePageAccess } from '../hooks/usePageAccess'
import { useDebounced, usePaging } from '../hooks/usePaging'
import { useUrlId, useUrlParams, useUrlPatch } from '../hooks/useUrlState'
import { mappingTypeLabel } from '../theme'
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

const STATUS_META: Record<TransferProposal['status'], { label: string; color: Tone }> = {
  pending: { label: 'Bekliyor', color: 'warning' },
  approved: { label: 'Onaylandı', color: 'info' },
  applied: { label: 'Uygulandı', color: 'success' },
  rejected: { label: 'Reddedildi', color: 'error' },
  cancelled: { label: 'İptal edildi', color: 'default' },
}

export const KIND_META: Record<string, { label: string; tone: Tone }> = {
  transfer: { label: 'Sertifika değişimi', tone: 'info' },
  date_fix: { label: 'Tarih güncelleme', tone: 'info' },
  server_add: { label: 'Sunucuya eklenen', tone: 'success' },
  server_remove: { label: 'Sunucudan kalkan', tone: 'warning' },
  trusted_add: { label: "Trust store'a ekleme", tone: 'default' },
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
  const kind = KIND_META[params.get('kind') ?? ''] ? params.get('kind')! : ''
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

  // Etkin filtre çipleri — seçim kutularında görünmeyenler dahil hepsi tek tıkla kaldırılır
  const chips = [
    ...(domainId !== null ? [{ key: 'domain', label: `Domain: ${selectedDomain?.domain}`, onDelete: () => patch({ domain: null }) }] : []),
    ...(kind ? [{ key: 'kind', label: `Tür: ${KIND_META[kind].label}`, onDelete: () => patch({ kind: null }) }] : []),
    ...(syTeam !== null ? [{ key: 'sy', label: `SY: ${syTeams.find((t) => t.id === syTeam)?.name ?? `#${syTeam}`}`, onDelete: () => patch({ sy: null }) }] : []),
    ...(via ? [{ key: 'via', label: `Kaynak: ${VIA_LABEL[via]}`, onDelete: () => patch({ via: null }) }] : []),
  ]
  const anyFilter = chips.length > 0 || liveOnly || mineOnly || !!urlQ
  const clearAll = () => { setQInput(''); patch({ domain: null, kind: null, sy: null, via: null, live: null, karar: null, q: null }) }
  const counts = data?.counts ?? {}
  const kindCounts = data?.facets?.kind ?? {}
  const SELECT_W = { xs: '100%', sm: 'auto' }

  return (
    <Box>
      <PageHeader title="Değişiklik Talepleri"
                  subtitle="JUMBO değişiklikleri yalnız önerir; talep domainin SY ekibi (veya admin) onaylayınca uygulanır, reddedilirse hiçbir şey değişmez." />

      <ListCard
        busy={isFetching && !isLoading}
        tabs={
          <StatusTabs value={status} onChange={(v) => patch({ status: v === 'pending' ? null : v })}
                      items={STATUS_TABS
                        .filter((t) => t.value !== 'approved' || (counts.approved ?? 0) > 0 || status === 'approved')
                        .map((t) => ({ value: t.value, label: t.label, count: counts[t.value] ?? 0,
                                       tone: t.value === 'pending' && (counts.pending ?? 0) > 0 ? 'warning' as const : undefined }))} />
        }
        toolbar={
          <>
            <SearchBox value={qInput} onChange={setQInput} placeholder="Domain, sertifika veya uygulama ara" width={300} />
            <Autocomplete size="small" sx={{ width: { xs: '100%', sm: 250 } }}
                          options={domainOptions ?? []} value={selectedDomain}
                          getOptionLabel={(d) => d.domain} isOptionEqualToValue={(a, b) => a.id === b.id}
                          onChange={(_, d) => patch({ domain: d ? String(d.id) : null })}
                          renderInput={(p) => <TextField {...p} label="Domain" placeholder="Tümü" slotProps={{ ...p.slotProps, inputLabel: { ...p.slotProps?.inputLabel, shrink: true } }} />} />
            <TextField select size="small" label="Tür" value={kind} sx={{ width: SELECT_W, minWidth: 190 }}
                       onChange={(e) => patch({ kind: e.target.value || null })}
                       slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}>
              <MenuItem value="">Tümü</MenuItem>
              {Object.entries(KIND_META).map(([k, m]) => (
                <MenuItem key={k} value={k} sx={{ display: 'flex', gap: 1.5 }}>
                  <Box sx={{ flexGrow: 1 }}>{m.label}</Box>
                  <Typography variant="caption" color="text.secondary">{kindCounts[k] ?? 0}</Typography>
                </MenuItem>
              ))}
            </TextField>
            <TextField select size="small" label="SY Ekip" value={syTeam !== null ? String(syTeam) : ''} sx={{ width: SELECT_W, minWidth: 170 }}
                       onChange={(e) => patch({ sy: e.target.value || null })}
                       slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}>
              <MenuItem value="">Tümü</MenuItem>
              {syTeams.map((t) => <MenuItem key={t.id} value={String(t.id)}>{t.name}</MenuItem>)}
            </TextField>
            <TextField select size="small" label="Kaynak" value={via} sx={{ width: SELECT_W, minWidth: 150 }}
                       onChange={(e) => patch({ via: e.target.value || null })}
                       slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}>
              <MenuItem value="">Tümü</MenuItem>
              {Object.entries(VIA_LABEL).map(([k, label]) => <MenuItem key={k} value={k}>{label}</MenuItem>)}
            </TextField>
            <Box sx={{ flexBasis: '100%', height: 0 }} />
            <ToggleChip label="Canlıda görüldü" selected={liveOnly} icon={<SensorsIcon />}
                        onChange={(v) => patch({ live: v ? '1' : null })} />
            <ToggleChip label="Yalnız karar verebileceklerim" selected={mineOnly} icon={<HowToRegOutlinedIcon />}
                        onChange={(v) => patch({ karar: v ? '1' : null })} />
            {anyFilter && (
              <Button size="small" color="inherit" startIcon={<FilterAltOffIcon fontSize="small" />}
                      onClick={clearAll} sx={{ color: 'text.secondary' }}>
                Filtreleri temizle
              </Button>
            )}
            <Box sx={{ flexGrow: 1 }} />
            <Typography variant="body2" color="text.secondary" sx={{ fontVariantNumeric: 'tabular-nums' }}>
              {(data?.total ?? 0).toLocaleString('tr-TR')} talep
            </Typography>
            <TextField select size="small" value={sortKey} sx={{ minWidth: 200 }}
                       aria-label="Sıralama"
                       onChange={(e) => patch({ sirala: e.target.value === 'new' ? null : e.target.value })}
                       slotProps={{ input: { startAdornment: <InputAdornment position="start"><SortIcon fontSize="small" /></InputAdornment> } }}>
              {SORTS.map((x) => <MenuItem key={x.value} value={x.value}>{x.label}</MenuItem>)}
            </TextField>
          </>
        }
        chips={chips.length ? <ActiveFilters chips={chips} onClearAll={clearAll} /> : undefined}
        footer={!isError && !isLoading && (data?.total ?? 0) > 0 && (
          <ListPagination total={data?.total ?? 0} page={paging.page} size={paging.size}
                          onPage={paging.setPage} onSize={paging.setSize} unit="talep" />
        )}
      >
        {isError ? (
          <Box sx={{ p: 2 }}><QueryError error={error} onRetry={() => refetch()} /></Box>
        ) : isLoading ? (
          <Box sx={{ p: 2 }}>{[0, 1, 2, 3].map((i) => <Skeleton key={i} height={56} />)}</Box>
        ) : items.length === 0 ? (
          <EmptyState
            title={anyFilter ? 'Bu filtrelerle eşleşen değişiklik talebi yok'
              : status === 'pending' ? 'Onay bekleyen değişiklik talebi yok' : 'Bu durumda değişiklik talebi yok'}
            hint={anyFilter ? 'Filtreleri kaldırarak tüm talepleri görebilirsiniz.' : undefined}
            action={anyFilter ? <Button size="small" onClick={clearAll}>Filtreleri temizle</Button> : undefined} />
        ) : (
          <TableContainer sx={{ overflowX: 'auto' }}>
            <Table size="small" sx={{ minWidth: 1040, tableLayout: 'fixed' }}>
              <colgroup>
                <col style={{ width: '31%' }} />
                <col style={{ width: '20%' }} />
                <col style={{ width: '14%' }} />
                <col style={{ width: '18%' }} />
                <col style={{ width: 252 }} />
              </colgroup>
              <TableHead>
                <TableRow>
                  <TableCell>Talep</TableCell>
                  <TableCell>Domain / Hedef</TableCell>
                  <TableCell>SY Ekip</TableCell>
                  <TableCell>Oluşturan</TableCell>
                  <TableCell align="right">{status === 'pending' ? 'Karar' : 'Durum'}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((p) => {
                  const meta = KIND_META[p.kind ?? 'transfer'] ?? KIND_META.transfer
                  return (
                    <TableRow key={p.id} hover onClick={() => setReviewId(p.id)} sx={{ cursor: 'pointer', verticalAlign: 'top' }}>
                      <TableCell sx={{ py: 1.5 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mb: 0.75, flexWrap: 'wrap' }}>
                          <StatusPill size="small" tone={meta.tone} label={meta.label} />
                          {p.live_seen && (
                            <Tooltip title="Yeni sertifika sunucuda canlı görüldü — onaylamak güvenli">
                              <span><StatusPill size="small" tone="success" label="Canlıda görüldü" /></span>
                            </Tooltip>
                          )}
                          {p.signal && (
                            <Typography variant="caption" color="text.secondary">
                              {p.signal === 'ski' ? 'aynı anahtar' : 'aynı CN + CA'}
                            </Typography>
                          )}
                        </Box>
                        <ChangeLine p={p} />
                      </TableCell>
                      <TableCell sx={{ py: 1.5 }}>
                        {p.kind === 'trusted_add' ? (
                          <>
                            <Typography variant="body2" noWrap sx={{ fontWeight: 500 }}>{p.app_name ?? 'Uygulama'}</Typography>
                            <Typography variant="caption" color="text.secondary">Trust store</Typography>
                          </>
                        ) : p.domain_id && p.domain_name ? (
                          <>
                            <Tooltip title="Yalnız bu domainin taleplerini göster">
                              <Link component="button" underline="hover" color="inherit" noWrap
                                    onClick={(e) => { e.stopPropagation(); patch({ domain: String(p.domain_id) }) }}
                                    sx={{ textAlign: 'left', fontWeight: 500, fontSize: 14, maxWidth: '100%', display: 'block' }}>
                                {p.domain_name}
                              </Link>
                            </Tooltip>
                            {p.mapping_type && (
                              <Typography variant="caption" color="text.secondary">{mappingTypeLabel(p.mapping_type)} bağlantısı</Typography>
                            )}
                          </>
                        ) : (
                          <Typography variant="body2">{p.domain_name ?? (p.app_dependency_id ? 'Trusted bağlantı' : '—')}</Typography>
                        )}
                      </TableCell>
                      <TableCell sx={{ py: 1.5 }}>
                        {p.sy_team_name
                          ? <Typography variant="body2" noWrap title={p.sy_team_name}>{p.sy_team_name}</Typography>
                          : <Tooltip title="Domainin SY sahibi yok — yalnız admin onaylar">
                              <span><StatusPill size="small" tone="warning" label="Sahipsiz" /></span>
                            </Tooltip>}
                      </TableCell>
                      <TableCell sx={{ py: 1.5 }}>
                        <Typography variant="body2" noWrap>{viaLabel(p.via, p.created_by)}</Typography>
                        <Typography variant="caption" color="text.secondary" noWrap component="div"
                                    title={proposerLine(p.created_by, p.created_at, p.created_by_name)}>
                          {proposerLine(p.created_by, p.created_at, p.created_by_name)}
                        </Typography>
                      </TableCell>
                      <TableCell align="right" sx={{ py: 1.5 }} onClick={(e) => e.stopPropagation()}>
                        {p.status !== 'pending' ? (
                          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                            <StatusPill size="small" tone={STATUS_META[p.status].color} label={STATUS_META[p.status].label} />
                            {p.decided_by && (
                              <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 0.5 }}>
                                {p.decided_by} · {fmtDay(p.decided_at)}
                              </Typography>
                            )}
                          </Box>
                        ) : p.can_decide ? (
                          <Box sx={{ display: 'inline-flex', gap: 0.75, alignItems: 'center' }}>
                            <Button size="small" onClick={() => setReviewId(p.id)}
                                    sx={{ color: 'text.secondary', px: 1, minWidth: 0 }}>
                              İncele
                            </Button>
                            <Button size="small" variant="outlined" color="inherit" disabled={decide.isPending}
                                    onClick={() => decide.mutate({ id: p.id, action: 'reject' })}
                                    sx={{ borderColor: 'divider', color: 'text.secondary', '&:hover': { color: 'error.main', borderColor: 'error.main' } }}>
                              Reddet
                            </Button>
                            <Button size="small" variant="contained" color="success" disableElevation
                                    startIcon={<CheckIcon fontSize="small" />} disabled={decide.isPending}
                                    onClick={() => decide.mutate({ id: p.id, action: 'approve' })}>
                              Onayla
                            </Button>
                          </Box>
                        ) : (
                          <Tooltip title="Bu talebi yalnız domainin SY ekibi üyesi veya admin karara bağlayabilir">
                            <Typography variant="caption" color="text.secondary"
                                        sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
                              <LockOutlinedIcon sx={{ fontSize: 14 }} /> Karar yetkiniz yok
                            </Typography>
                          </Tooltip>
                        )}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </ListCard>

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

/** Talebin ne değiştireceği — türüne göre tek bakışta okunur iki satır. */
function ChangeLine({ p }: { p: TransferProposal }) {
  const strong = (t?: string | null) => (
    <Typography variant="body2" noWrap title={t ?? undefined} sx={{ fontWeight: 600, minWidth: 0 }}>{t ?? '—'}</Typography>
  )
  const sub = (t: ReactNode) => <Typography variant="caption" color="text.secondary" component="div" noWrap>{t}</Typography>
  switch (p.kind) {
    case 'date_fix':
      return <>{strong(p.new_cert_name)}{sub(p.cert_valid_to
        ? <>Bitiş tarihi {fmtDay(p.record_valid_to)} → {fmtDay(p.cert_valid_to)} olarak düzeltilecek</>
        : <>Kayıttaki bitiş {fmtDay(p.record_valid_to)}, sertifikadaki tarihle düzeltilecek</>)}</>
    case 'server_add':
      return <>{strong(p.new_cert_name)}{sub('Sunucuda görüldü, domaine bağlanacak')}</>
    case 'server_remove':
      return <>{strong(p.new_cert_name)}{sub('Sunucu artık sunmuyor, bağlantı kaldırılacak')}</>
    case 'trusted_add':
      return <>{strong(p.new_cert_name)}{sub("Trust store'a eklenecek, eski sertifika kalır")}</>
    default:
      return (
        <Box sx={{ display: 'grid', gridTemplateColumns: 'auto minmax(0,1fr)', columnGap: 1, rowGap: 0.25, alignItems: 'baseline' }}>
          <Typography variant="caption" color="text.secondary">Eski</Typography>
          <Typography variant="body2" color="text.secondary" noWrap title={p.old_cert_name ?? undefined}>{p.old_cert_name ?? '—'}</Typography>
          <Typography variant="caption" color="text.secondary">Yeni</Typography>
          {strong(p.new_cert_name)}
        </Box>
      )
  }
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
