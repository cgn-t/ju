import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import {
  Box, Button, ButtonBase, Skeleton, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { TeamAttentionItem, TeamDetail } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import CertificateDetailDrawer from '../components/CertificateDetailDrawer'
import { fmtDate, StatusPill, type Tone } from '../components/DetailCards'
import DomainDetailDrawer from '../components/DomainDetailDrawer'
import { DaysLeftPill, EmptyState } from '../components/ListKit'
import PageHeader from '../components/PageHeader'
import QueryError from '../components/QueryError'
import { dayText, Panel, ProposalList, SummaryTile, TEAM_HEALTH, TILE_GRID } from '../components/TeamSummaryKit'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useUrlId } from '../hooks/useUrlState'

const ATTENTION_TONE: Record<TeamAttentionItem['kind'], Tone> = {
  live: 'error', no_cert: 'warning', policy: 'warning', no_pem: 'default',
}

/** Tek ekibin özeti: Yönetici Panosu'ndan satıra tıklayınca ya da Anasayfa'daki Ekibim'den açılır. */
export default function TeamSummary() {
  const { teamId } = useParams()
  const navigate = useNavigate()
  const { role } = useAuth()
  const isManager = role === 'admin' || role === 'allviewer'
  const [certId, setCertId] = useUrlId('cert')
  const [domainId, setDomainId] = useUrlId('domain')
  const { data, isLoading, isError, error, refetch } = useQuery<TeamDetail>({
    queryKey: ['summary', 'team', teamId],
    queryFn: async () => (await api.get(`/summary/teams/${teamId}`)).data,
    retry: false,   // 403 (başka ekip) / 404 hemen gösterilsin
  })
  useDocumentTitle(data ? `${data.team} ekibi` : 'Ekip özeti')

  const back = (
    <Button size="small" startIcon={<ArrowBackIcon />} onClick={() => navigate(isManager ? '/overview' : '/')} sx={{ mb: 1 }}>
      {isManager ? 'Yönetici Panosu' : 'Anasayfa'}
    </Button>
  )
  if (isError) return <Box>{back}<QueryError error={error} onRetry={() => refetch()} /></Box>
  if (isLoading || !data) return <Box>{back}<Skeleton variant="rounded" height={520} /></Box>

  const health = TEAM_HEALTH[data.status]
  const meta = [data.email ? `Ekip maili: ${data.email}` : 'Ekip maili tanımlı değil',
                `${data.members} kişi`, `${data.applications} uygulama`].join(' · ')
  return (
    <Box>
      {back}
      <PageHeader title={data.team} subtitle={meta}
                  actions={<StatusPill tone={health.tone} label={health.label} />} />
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
        <Box sx={{ ...TILE_GRID, gridTemplateColumns: { xs: '1fr 1fr', md: 'repeat(3, 1fr)', lg: 'repeat(6, 1fr)' } }}>
          <SummaryTile label="Domain" value={data.domains} />
          <SummaryTile label="Aktif sertifika" value={data.certificates} />
          <SummaryTile label="Süresi dolmuş" value={data.expired} tone={data.expired ? 'error' : 'default'} />
          <SummaryTile label={`${data.expiring_soon_days} gün içinde`} value={data.expiring_soon}
                       tone={data.expiring_soon ? 'warning' : 'default'}
                       sub={data.nearest_days !== null && data.nearest_days !== undefined ? `En yakını ${dayText(data.nearest_days)} sonra` : undefined} />
          <SummaryTile label="Bekleyen talep" value={data.pending_proposals} tone={data.pending_proposals ? 'info' : 'default'}
                       onClick={() => navigate(`/proposals?sy=${data.team_id}`)} />
          <SummaryTile label="EŞLEŞMİYOR" value={data.live_problems} tone={data.live_problems ? 'error' : 'default'} sub="domain" />
        </Box>

        <Panel title={`Süresi dolmuş ve ${data.expiring_soon_days} gün içinde bitecek sertifikalar`} pad={false}>
          {data.certificates_attention.length === 0 ? (
            <EmptyState title="Yakında biten sertifika yok" hint="Bu ekibin tüm sertifikaları şu an güncel." />
          ) : (
            <TableContainer sx={{ overflowX: 'auto' }}>
              <Table size="small" sx={{ minWidth: 820 }}>
                <TableHead>
                  <TableRow>
                    <TableCell>Sertifika</TableCell>
                    <TableCell>Domain</TableCell>
                    <TableCell>ValidTo</TableCell>
                    <TableCell>Son uyarı maili</TableCell>
                    <TableCell>Açık talep</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {data.certificates_attention.map((c) => (
                    <TableRow key={c.id} hover onClick={() => setCertId(c.id)} sx={{ cursor: 'pointer' }}>
                      <TableCell sx={{ fontWeight: 600 }}>{c.name}</TableCell>
                      <TableCell>{c.domains.length ? c.domains.join(', ') : '—'}</TableCell>
                      <TableCell><DaysLeftPill days={c.days_left} date={c.valid_to} /></TableCell>
                      <TableCell sx={{ color: c.last_mail_at ? 'text.primary' : 'text.secondary', whiteSpace: 'nowrap' }}>
                        {c.last_mail_at ? fmtDate(c.last_mail_at) : 'Henüz gönderilmedi'}
                      </TableCell>
                      <TableCell>{c.open_proposals.length ? c.open_proposals.join(', ') : '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Panel>

        <Box sx={{ display: 'grid', gap: 2.5, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' } }}>
          <Panel title="Onay bekleyen talepler">
            <ProposalList items={data.pending} onOpen={(id) => navigate(`/proposals?review=${id}`)} />
          </Panel>
          <Panel title="Dikkat isteyen kayıtlar">
            {data.attention.length === 0 ? (
              <Typography variant="body2" color="text.secondary">Dikkat isteyen kayıt yok.</Typography>
            ) : data.attention.map((a, i) => (
              <ButtonBase key={`${a.kind}-${a.domain_id ?? a.certificate_id}`}
                          onClick={() => (a.domain_id ? setDomainId(a.domain_id) : a.certificate_id && setCertId(a.certificate_id))}
                          sx={{ width: '100%', display: 'flex', justifyContent: 'space-between', gap: 2, py: 1, textAlign: 'left',
                                borderTop: i ? 1 : 0, borderColor: 'divider', '&:hover': { color: 'primary.main' } }}>
                <Typography variant="body2" noWrap sx={{ fontWeight: 600, minWidth: 0 }}>{a.name}</Typography>
                <StatusPill size="small" tone={ATTENTION_TONE[a.kind]} label={a.detail} />
              </ButtonBase>
            ))}
          </Panel>
        </Box>
      </Box>
      <CertificateDetailDrawer certId={certId} onClose={() => setCertId(null)} onSelectCert={setCertId} />
      <DomainDetailDrawer domainId={domainId} onClose={() => setDomainId(null)} />
    </Box>
  )
}
