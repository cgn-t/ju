import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import GppMaybeIcon from '@mui/icons-material/GppMaybe'
import PercentIcon from '@mui/icons-material/Percent'
import RuleIcon from '@mui/icons-material/Rule'
import {
  Alert, Box, Chip, Grid, Paper, Skeleton, Stack, Table, TableBody, TableCell, TableHead,
  TableRow, Tooltip, Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api } from '../api/client'
import type { PolicyReport } from '../api/types'
import PageHeader from '../components/PageHeader'
import QueryError from '../components/QueryError'
import StatCard from '../components/StatCard'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { usePageAccess } from '../hooks/usePageAccess'
import { MONO_FONT, daysLeftColor, daysLeftLabel } from '../theme'

const RULE_LABELS: Record<string, string> = {
  untrusted_issuer: 'Güvenilmeyen Issuer',
  weak_key: 'Zayıf Anahtar',
  weak_signature: 'Zayıf İmza',
  excessive_validity: 'Aşırı Ömür',
}

const SEVERITY: Record<string, { label: string; color: 'error' | 'warning' | 'default' }> = {
  high: { label: 'Yüksek', color: 'error' },
  medium: { label: 'Orta', color: 'warning' },
  low: { label: 'Düşük', color: 'default' },
}

export default function Policy() {
  useDocumentTitle('Uyum')
  const { policy: canSee } = usePageAccess()
  const [ruleFilter, setRuleFilter] = useState<string | null>(null)

  const { data, isLoading, isError, error, refetch } = useQuery<PolicyReport>({
    queryKey: ['policy', 'report'],
    queryFn: async () => (await api.get('/policy/report')).data,
    enabled: canSee,
  })

  const rules = useMemo(() => Object.entries(data?.rule_counts ?? {})
    .sort((a, b) => b[1] - a[1]), [data])
  const rows = (data?.violations ?? []).filter((v) => (ruleFilter ? v.rules.includes(ruleFilter) : true))
  const ratio = data && data.total_evaluated > 0
    ? Math.round((data.compliant / data.total_evaluated) * 100) : 100

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

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard icon={<RuleIcon />} label="Değerlendirilen" value={data?.total_evaluated ?? 0}
                    color="#607d8b" onClick={() => setRuleFilter(null)} />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard icon={<CheckCircleIcon />} label="Uyumlu" value={data?.compliant ?? 0} color="#2e7d32" />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard icon={<GppMaybeIcon />} label="Uyumsuz" value={data?.non_compliant ?? 0} color="#c62828"
                    onClick={() => setRuleFilter(null)} />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard icon={<PercentIcon />} label="Uyum Oranı" value={ratio} color="#1565c0" />
        </Grid>
      </Grid>

      {rules.length > 0 && (
        <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: 'wrap', rowGap: 1 }}>
          <Typography variant="body2" color="text.secondary" sx={{ alignSelf: 'center' }}>Kurallar:</Typography>
          {rules.map(([rule, count]) => (
            <Chip key={rule} size="small" label={`${RULE_LABELS[rule] ?? rule} · ${count}`}
                  color={ruleFilter === rule ? 'primary' : 'default'}
                  variant={ruleFilter === rule ? 'filled' : 'outlined'}
                  onClick={() => setRuleFilter(ruleFilter === rule ? null : rule)} />
          ))}
        </Stack>
      )}

      <Paper variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Sertifika</TableCell>
              <TableCell>Tür</TableCell>
              <TableCell>İhlaller</TableCell>
              <TableCell>Anahtar</TableCell>
              <TableCell>İmza</TableCell>
              <TableCell>Bitiş</TableCell>
              <TableCell>Önem</TableCell>
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
                <CheckCircleIcon sx={{ fontSize: 40, color: 'success.main', mb: 1 }} />
                <Typography color="text.secondary">
                  {(data?.non_compliant ?? 0) === 0
                    ? 'Tüm sertifikalar politikaya uyumlu.'
                    : 'Bu filtreye uyan ihlal yok.'}
                </Typography>
              </TableCell></TableRow>
            )}
            {rows.map((v) => (
              <TableRow key={v.certificate_id} hover>
                <TableCell sx={{ fontWeight: 600, wordBreak: 'break-word' }}>
                  {v.name || '—'}
                  {v.issuer && (
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                      {v.issuer}
                    </Typography>
                  )}
                </TableCell>
                <TableCell><Chip size="small" variant="outlined" label={v.cert_type || '—'} /></TableCell>
                <TableCell>
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                    {v.rules.map((r, i) => (
                      <Tooltip key={r} title={v.details[i] || ''}>
                        <Chip size="small" color="warning" variant="outlined" label={RULE_LABELS[r] ?? r} />
                      </Tooltip>
                    ))}
                  </Box>
                </TableCell>
                <TableCell sx={{ fontFamily: MONO_FONT, fontSize: 12, whiteSpace: 'nowrap' }}>
                  {v.public_key_type ? `${v.public_key_type}${v.key_size ? ` ${v.key_size}` : ''}` : '—'}
                </TableCell>
                <TableCell sx={{ fontFamily: MONO_FONT, fontSize: 12 }}>{v.signature_hash || '—'}</TableCell>
                <TableCell>
                  <Chip size="small" color={daysLeftColor(v.days_left)} label={daysLeftLabel(v.days_left)} />
                </TableCell>
                <TableCell>
                  <Chip size="small" color={SEVERITY[v.severity]?.color ?? 'default'}
                        label={SEVERITY[v.severity]?.label ?? v.severity} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
    </Box>
  )
}

// Nav rozeti: uyumsuz sertifika sayısı (yalnız Uyum sayfasını görebilenlere — bkz. usePageAccess)
export function usePolicyViolationCount() {
  const { policy: canSee } = usePageAccess()
  const { data } = useQuery<PolicyReport>({
    queryKey: ['policy', 'report'],
    queryFn: async () => (await api.get('/policy/report')).data,
    enabled: canSee,
    refetchInterval: 60_000,
  })
  return data?.non_compliant ?? 0
}
