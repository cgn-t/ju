import DownloadIcon from '@mui/icons-material/Download'
import { Box, Button, Skeleton, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { TeamOverview } from '../api/types'
import { StatusPill } from '../components/DetailCards'
import PageHeader from '../components/PageHeader'
import QueryError from '../components/QueryError'
import {
  dayText, exportTeamRows, Panel, ProposalList, SummaryTile, TEAM_HEALTH, TeamSummaryTable, TILE_GRID,
  UpcomingMonths,
} from '../components/TeamSummaryKit'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

/** Genel Durum: tüm ekiplerin sertifika durumu (admin ve Genel İzleyici). */
export default function ManagerBoard() {
  useDocumentTitle('Genel Durum')
  const navigate = useNavigate()
  const { data, isLoading, isError, error, refetch } = useQuery<TeamOverview>({
    queryKey: ['summary', 'teams'],
    queryFn: async () => (await api.get('/summary/teams')).data,
  })
  const generated = data ? new Date(data.generated_at).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' }) : ''
  const header = (
    <PageHeader title="Genel Durum"
                subtitle={data ? `Tüm ekiplerin sertifika durumu · ${generated}` : 'Tüm ekiplerin sertifika durumu'}
                actions={data && (
                  <Button variant="outlined" startIcon={<DownloadIcon />}
                          onClick={() => exportTeamRows(data.teams, data.expiring_soon_days)}>
                    Excel'e indir
                  </Button>
                )} />
  )
  if (isError) return <Box>{header}<QueryError error={error} onRetry={() => refetch()} /></Box>
  if (isLoading || !data) return <Box>{header}<Skeleton variant="rounded" height={520} /></Box>

  const t = data.totals
  const sc = t.status_counts
  return (
    <Box>
      {header}
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
        <Box sx={TILE_GRID}>
          <SummaryTile label="Süresi dolmuş sertifika" value={t.expired} tone={t.expired ? 'error' : 'default'}
                       sub={t.expired ? `${t.expired_teams} ekipte` : 'Yok'} onClick={() => navigate('/certificates?f_valid=expired')} />
          <SummaryTile label={`${data.expiring_soon_days} gün içinde bitecek`} value={t.expiring_soon}
                       tone={t.expiring_soon ? 'warning' : 'default'}
                       sub={t.nearest_days !== null && t.nearest_days !== undefined ? `En yakını ${dayText(t.nearest_days)} sonra` : undefined}
                       onClick={() => navigate('/certificates?f_valid=expiring')} />
          <SummaryTile label="Onay bekleyen talep" value={t.pending_proposals} tone={t.pending_proposals ? 'info' : 'default'}
                       sub={t.oldest_pending_days ? `En eskisi ${t.oldest_pending_days} gündür bekliyor` : undefined}
                       onClick={() => navigate('/proposals')} />
          <SummaryTile label="Canlıda EŞLEŞMİYOR" value={t.live_problems} tone={t.live_problems ? 'error' : 'default'}
                       sub="domain (ayrıntısı ekip satırında)" />
          <SummaryTile label="Eksik bilgili kayıt" value={t.missing_info}
                       sub={[t.missing_detail.domains_without_team ? `${t.missing_detail.domains_without_team} domainin ekibi yok` : '',
                             t.missing_detail.no_pem ? `${t.missing_detail.no_pem} sertifikada PEM yok` : '']
                         .filter(Boolean).join(' · ') || undefined} />
        </Box>

        <Panel title="Ekiplere göre durum" pad={false} aside={
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            {(['critical', 'warning', 'ok'] as const).map((s) => (
              <StatusPill key={s} size="small" tone={TEAM_HEALTH[s].tone} label={`${sc[s] ?? 0} ekip ${TEAM_HEALTH[s].label.toLocaleLowerCase('tr')}`} />
            ))}
          </Box>
        }>
          <TeamSummaryTable rows={data.teams} soonDays={data.expiring_soon_days} onOpen={(id) => navigate(`/teams/${id}`)} />
          <Typography variant="caption" color="text.secondary" component="p" sx={{ px: 2, py: 1.25, m: 0, borderTop: 1, borderColor: 'divider' }}>
            En riskli ekip en üstte. Satıra tıklayınca ekibin ayrıntısı açılır.
          </Typography>
        </Panel>

        <Box sx={{ display: 'grid', gap: 2.5, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' } }}>
          <Panel title="Önümüzdeki 90 günde bitecekler"><UpcomingMonths months={data.upcoming_months} /></Panel>
          <Panel title="En uzun bekleyen talepler">
            <ProposalList items={data.oldest_proposals} showTeam onOpen={(id) => navigate(`/proposals?review=${id}`)} />
          </Panel>
        </Box>
      </Box>
    </Box>
  )
}
