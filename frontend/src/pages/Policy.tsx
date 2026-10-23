import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import GppMaybeIcon from '@mui/icons-material/GppMaybe'
import PercentIcon from '@mui/icons-material/Percent'
import RuleIcon from '@mui/icons-material/Rule'
import SortIcon from '@mui/icons-material/Sort'
import {
  Alert, Box, Grid, InputAdornment, MenuItem, Skeleton, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, TextField, Tooltip, Typography,
} from '@mui/material'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { PolicyCounts, PolicyViolationPage } from '../api/types'
import CertificateDetailDrawer from '../components/CertificateDetailDrawer'
import { CERT_TYPE_FULL, StatusPill, type Tone } from '../components/DetailCards'
import { DaysLeftPill, EmptyState, ListCard, SearchBox, StatusTabs } from '../components/ListKit'
import ListPagination from '../components/ListPagination'
import PageHeader from '../components/PageHeader'
import QueryError from '../components/QueryError'
import StatCard from '../components/StatCard'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { usePageAccess } from '../hooks/usePageAccess'
import { useDebounced, usePaging } from '../hooks/usePaging'
import { useUrlId, useUrlState } from '../hooks/useUrlState'
import { MONO_FONT } from '../theme'

const RULE_LABELS: Record<string, string> = {
  untrusted_issuer: 'İzin Listesi Dışı CA',
  weak_key: 'Zayıf Anahtar',
  weak_signature: 'Zayıf İmza',
  excessive_validity: 'Aşırı Ömür',
}

const SEVERITY: Record<string, { label: string; tone: Tone }> = {
  high: { label: 'Yüksek', tone: 'error' },
  medium: { label: 'Orta', tone: 'warning' },
  low: { label: 'Düşük', tone: 'default' },
}

const SORTS = [
  { value: 'severity', label: 'Önem: yüksekten düşüğe', sort: 'severity', dir: 'asc' },
  { value: 'valid_to', label: 'ValidTo: en yakın önce', sort: 'valid_to', dir: 'asc' },
  { value: 'name', label: 'Ad: A → Z', sort: 'name', dir: 'asc' },
] as const

export default function Policy() {
  useDocumentTitle('Uyum')
  const { policy: canSee } = usePageAccess()
  const [rule, setRule] = useUrlState<string>('rule', '')
  const [severity, setSeverity] = useUrlState<string>('onem', '')
  const [sortKey, setSortKey] = useUrlState<string>('sirala', 'severity')
  const [search, setSearch] = useUrlState<string>('q', '')
  const [certId, setCertId] = useUrlId('cert')
  const sort = SORTS.find((s) => s.value === sortKey) ?? SORTS[0]

  // Binlerce ihlalde sayfa hızlı açılsın: sunucu yalnız görünen sayfayı döner.
  const filterParams = useDebounced(JSON.stringify({
    rule: rule || undefined, severity: severity || undefined, q: search.trim() || undefined,
    sort: sort.sort, dir: sort.dir,
  }))
  const paging = usePaging(filterParams)
  const { data, isLoading, isFetching, isError, error, refetch } = useQuery<PolicyViolationPage>({
    queryKey: ['policy', 'page', filterParams, paging.page, paging.size],
    queryFn: async () => (await api.get('/policy/violations/page', {
      params: { ...JSON.parse(filterParams), page: paging.page, size: paging.size },
    })).data,
    enabled: canSee,
    placeholderData: keepPreviousData,
  })
  const items = data?.items ?? []
  const ratio = data && data.total_evaluated > 0
    ? Math.round((data.compliant / data.total_evaluated) * 100) : 100
  const ruleTabs = Object.entries(data?.rule_counts ?? {}).sort((a, b) => b[1] - a[1])
  const sev = data?.severity_counts ?? {}
  const filtered = !!rule || !!severity || !!search.trim()

  return (
    <Box>
      <PageHeader
        title="Uyum"
        subtitle="Envanterdeki sertifikaları politikaya göre denetler: CA allowlist, zayıf anahtar/imza, aşırı geçerlilik süresi"
      />

      {data && !data.enabled && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Uyum değerlendirmesi <b>kapalı</b> (Ayarlar → Uyum). Aşağıdaki bulgular yine de mevcut
          envantere göre hesaplanır; kuralları düzenlemek için politikayı açın.
        </Alert>
      )}

      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard icon={<RuleIcon />} label="Değerlendirilen" value={(data?.total_evaluated ?? 0).toLocaleString('tr-TR')} color="#607d8b" />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard icon={<CheckCircleIcon />} label="Uyumlu" value={(data?.compliant ?? 0).toLocaleString('tr-TR')} color="#2e7d32" />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard icon={<GppMaybeIcon />} label="Uyumsuz" value={(data?.non_compliant ?? 0).toLocaleString('tr-TR')} color="#c62828"
                    onClick={() => { setRule(''); setSeverity('') }} />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard icon={<PercentIcon />} label="Uyum Oranı" value={`%${ratio}`} color="#1565c0" />
        </Grid>
      </Grid>

      <ListCard
        busy={isFetching && !isLoading}
        tabs={
          <StatusTabs value={rule} onChange={setRule} items={[
            { value: '', label: 'Tüm ihlaller', count: data?.non_compliant ?? 0 },
            ...ruleTabs.map(([r, n]) => ({ value: r, label: RULE_LABELS[r] ?? r, count: n })),
          ]} />
        }
        toolbar={
          <>
            <SearchBox value={search} onChange={setSearch} placeholder="Sertifika adı veya Issuer ara" width={320} />
            <TextField select size="small" label="Önem" value={severity} onChange={(e) => setSeverity(e.target.value)}
                       sx={{ minWidth: 170 }} slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}>
              <MenuItem value="">Tümü</MenuItem>
              {Object.entries(SEVERITY).map(([k, m]) => (
                <MenuItem key={k} value={k} sx={{ display: 'flex', gap: 1.5 }}>
                  <Box sx={{ flexGrow: 1 }}>{m.label}</Box>
                  <Typography variant="caption" color="text.secondary">{sev[k] ?? 0}</Typography>
                </MenuItem>
              ))}
            </TextField>
            <Box sx={{ flexGrow: 1 }} />
            <Typography variant="body2" color="text.secondary" sx={{ fontVariantNumeric: 'tabular-nums' }}>
              {(data?.total ?? 0).toLocaleString('tr-TR')} sertifika
            </Typography>
            <TextField select size="small" value={sort.value} sx={{ minWidth: 220 }} aria-label="Sıralama"
                       onChange={(e) => setSortKey(e.target.value)}
                       slotProps={{ input: { startAdornment: <InputAdornment position="start"><SortIcon fontSize="small" /></InputAdornment> } }}>
              {SORTS.map((s) => <MenuItem key={s.value} value={s.value}>{s.label}</MenuItem>)}
            </TextField>
          </>
        }
        footer={!isError && !isLoading && (data?.total ?? 0) > 0 && (
          <ListPagination total={data?.total ?? 0} page={paging.page} size={paging.size}
                          onPage={paging.setPage} onSize={paging.setSize} unit="sertifika" />
        )}
      >
        {isError ? (
          <Box sx={{ p: 2 }}><QueryError error={error} onRetry={() => refetch()} /></Box>
        ) : isLoading ? (
          <Box sx={{ p: 2 }}>{[0, 1, 2, 3].map((i) => <Skeleton key={i} height={48} />)}</Box>
        ) : items.length === 0 ? (
          <EmptyState title={(data?.non_compliant ?? 0) === 0 ? 'Tüm sertifikalar politikaya uyumlu' : 'Bu filtreye uyan ihlal yok'}
                      hint={filtered ? 'Filtreleri değiştirerek diğer ihlalleri görebilirsiniz.' : undefined} />
        ) : (
          <TableContainer sx={{ overflowX: 'auto' }}>
            <Table size="small" sx={{ minWidth: 960 }}>
              <TableHead>
                <TableRow>
                  <TableCell>Sertifika</TableCell>
                  <TableCell>Type</TableCell>
                  <TableCell>İhlaller</TableCell>
                  <TableCell>Public Key</TableCell>
                  <TableCell>Signature</TableCell>
                  <TableCell>ValidTo</TableCell>
                  <TableCell>Önem</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((v) => (
                  <TableRow key={v.certificate_id} hover sx={{ cursor: 'pointer' }}
                            onClick={() => setCertId(v.certificate_id)}>
                    <TableCell sx={{ maxWidth: 360 }}>
                      <Typography variant="body2" noWrap title={v.name ?? undefined} sx={{ fontWeight: 600 }}>{v.name || '—'}</Typography>
                      {v.issuer && (
                        <Typography variant="caption" color="text.secondary" noWrap component="div" title={v.issuer}>{v.issuer}</Typography>
                      )}
                    </TableCell>
                    <TableCell><Typography variant="body2">{CERT_TYPE_FULL[v.cert_type ?? ''] ?? v.cert_type ?? '—'}</Typography></TableCell>
                    <TableCell>
                      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                        {v.rules.map((r, i) => (
                          <Tooltip key={r} title={v.details[i] || ''}>
                            <span><StatusPill size="small" tone="warning" label={RULE_LABELS[r] ?? r} /></span>
                          </Tooltip>
                        ))}
                      </Box>
                    </TableCell>
                    <TableCell sx={{ fontFamily: MONO_FONT, fontSize: 12, whiteSpace: 'nowrap' }}>
                      {v.public_key_type ? `${v.public_key_type}${v.key_size ? ` ${v.key_size}` : ''}` : '—'}
                    </TableCell>
                    <TableCell sx={{ fontFamily: MONO_FONT, fontSize: 12 }}>{v.signature_hash || '—'}</TableCell>
                    <TableCell><DaysLeftPill days={v.days_left} date={v.valid_to} /></TableCell>
                    <TableCell>
                      <StatusPill size="small" tone={SEVERITY[v.severity]?.tone ?? 'default'} label={SEVERITY[v.severity]?.label ?? v.severity} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </ListCard>

      <CertificateDetailDrawer certId={certId} onClose={() => setCertId(null)}
                               onSelectCert={(id) => setCertId(id)} />
    </Box>
  )
}

// Nav rozeti: uyumsuz sertifika sayısı (yalnız Uyum sayfasını görebilenlere — bkz. usePageAccess).
// Hafif sayaç ucu: ihlal listesi her dakika taşınmaz.
export function usePolicyViolationCount() {
  const { policy: canSee } = usePageAccess()
  const { data } = useQuery<PolicyCounts>({
    queryKey: ['policy', 'counts'],
    queryFn: async () => (await api.get('/policy/counts')).data,
    enabled: canSee,
    refetchInterval: 60_000,
  })
  return data?.non_compliant ?? 0
}
