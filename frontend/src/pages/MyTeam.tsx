import { Box } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { TeamOverview } from '../api/types'
import { EmptyState } from '../components/ListKit'
import MyTeamSection from '../components/MyTeamSection'
import PageHeader from '../components/PageHeader'
import QueryError from '../components/QueryError'
import { dayText, SummaryTile, TILE_GRID } from '../components/TeamSummaryKit'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

/** Ekibim (editör / Ekip İzleyici): kendi ekibinin özeti, ekipten beklenenler ve yenileme takvimi. */
export default function MyTeam() {
  useDocumentTitle('Ekibim')
  const navigate = useNavigate()
  const { data, isError, error, refetch } = useQuery<TeamOverview>({
    queryKey: ['summary', 'teams'],
    queryFn: async () => (await api.get('/summary/teams')).data,
  })
  const teams = data?.teams ?? []
  const single = teams.length === 1 ? teams[0] : null
  const header = (
    <PageHeader title={teams.length > 1 ? 'Ekiplerim' : 'Ekibim'}
                subtitle={teams.length ? `${teams.map((r) => r.team).join(', ')} · ekibin yapması gerekenler` : 'Ekibin yapması gerekenler'} />
  )
  if (isError) return <Box>{header}<QueryError error={error} onRetry={() => refetch()} /></Box>
  if (data && !teams.length) {
    return <Box>{header}<EmptyState title="Ekibinize ait kayıt yok" hint="Ekibinize bağlı domain veya sertifika olduğunda burada görünür." /></Box>
  }

  const t = data?.totals
  return (
    <Box>
      {header}
      {t && (
        <Box sx={{ ...TILE_GRID, gridTemplateColumns: { xs: '1fr 1fr', md: 'repeat(3, 1fr)', lg: 'repeat(5, 1fr)' }, mb: 2.5 }}>
          <SummaryTile label="Aktif sertifika" value={t.certificates} sub={`${t.domains} domain`} />
          <SummaryTile label="Süresi dolmuş" value={t.expired} tone={t.expired ? 'error' : 'default'}
                       onClick={() => navigate('/certificates?f_valid=expired')} />
          <SummaryTile label={`${data.expiring_soon_days} gün içinde`} value={t.expiring_soon}
                       tone={t.expiring_soon ? 'warning' : 'default'}
                       sub={t.nearest_days !== null && t.nearest_days !== undefined ? `En yakını ${dayText(t.nearest_days)} sonra` : undefined}
                       onClick={() => navigate('/certificates?f_valid=expiring')} />
          <SummaryTile label="Bekleyen talep" value={t.pending_proposals} tone={t.pending_proposals ? 'info' : 'default'}
                       onClick={() => navigate(single ? `/proposals?sy=${single.team_id}` : '/proposals')} />
          <SummaryTile label="EŞLEŞMİYOR" value={t.live_problems} tone={t.live_problems ? 'error' : 'default'} sub="domain"
                       onClick={single ? () => navigate(`/teams/${single.team_id}`) : undefined} />
        </Box>
      )}
      <MyTeamSection />
    </Box>
  )
}
