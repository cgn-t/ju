import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import { Box, ButtonBase, Skeleton, Typography } from '@mui/material'
import { alpha } from '@mui/material/styles'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { TeamOverview } from '../api/types'
import type { Tone } from './DetailCards'
import { monthLabel, Panel, TeamSummaryTable } from './TeamSummaryKit'

function Todo({ n, text, tone, onClick }: { n: number; text: string; tone: Tone; onClick: () => void }) {
  return (
    <ButtonBase onClick={onClick}
                sx={(t) => {
                  const c = tone === 'default' ? t.palette.text.secondary : t.palette[tone].main
                  return {
                    width: '100%', justifyContent: 'flex-start', gap: 1.5, px: 1.75, py: 1.25, borderRadius: '10px',
                    textAlign: 'left', bgcolor: alpha(c, t.palette.mode === 'dark' ? 0.16 : 0.08),
                    color: tone === 'default' ? 'text.primary' : t.palette.mode === 'dark' ? t.palette[tone].light : t.palette[tone].dark,
                    '&:hover': { bgcolor: alpha(c, t.palette.mode === 'dark' ? 0.24 : 0.14) },
                  }
                }}>
      <Typography sx={{ fontSize: 20, fontWeight: 800, minWidth: 30 }}>{n}</Typography>
      <Typography variant="body2" sx={{ flexGrow: 1, fontWeight: 500 }}>{text}</Typography>
      <ChevronRightIcon fontSize="small" sx={{ opacity: 0.6 }} />
    </ButtonBase>
  )
}

/** Anasayfa 'Ekibim' bölümü: ekip kullanıcısına kendi ekibinden beklenenler + yenileme takvimi. */
export default function MyTeamSection() {
  const navigate = useNavigate()
  const { data, isLoading } = useQuery<TeamOverview>({
    queryKey: ['summary', 'teams'],
    queryFn: async () => (await api.get('/summary/teams')).data,
  })
  if (isLoading) return <Skeleton variant="rounded" height={220} sx={{ mb: 3 }} />
  if (!data || !data.teams.length) return null

  const t = data.totals
  const single = data.teams.length === 1 ? data.teams[0] : null
  // Tek ekip: ekip özetine; birden çok ekip: ilgili listeye (Ekiplerim tablosu da hemen altta)
  const go = (multiPath: string) => () => navigate(single ? `/teams/${single.team_id}` : multiPath)
  const todos = [
    t.expired ? { n: t.expired, tone: 'error' as Tone, text: 'sertifikanın süresi doldu, yenilenmesi gerekiyor', go: go('/certificates?f_valid=expired') } : null,
    t.expiring_soon ? { n: t.expiring_soon, tone: 'warning' as Tone, text: `sertifika ${data.expiring_soon_days} gün içinde bitiyor`, go: go('/certificates?f_valid=expiring') } : null,
    t.pending_proposals ? { n: t.pending_proposals, tone: 'info' as Tone,
      text: `değişiklik talebi onay bekliyor${t.oldest_pending_days ? ` (en eskisi ${t.oldest_pending_days} gündür)` : ''}`,
      go: () => navigate(single ? `/proposals?sy=${single.team_id}` : '/proposals') } : null,
    t.live_problems ? { n: t.live_problems, tone: 'error' as Tone, text: 'domainde canlı doğrulama EŞLEŞMİYOR', go: go('/domains') } : null,
    t.policy_violations ? { n: t.policy_violations, tone: 'default' as Tone, text: 'sertifikada uyum ihlali var', go: go('/policy') } : null,
    t.missing_info ? { n: t.missing_info, tone: 'default' as Tone, text: 'kayıtta eksik bilgi var (PEM, sertifika ya da ekip maili)', go: go('/domains') } : null,
  ].filter(Boolean) as { n: number; tone: Tone; text: string; go: () => void }[]

  // Yenileme takvimi: önümüzdeki 90 gün, ay ay
  const byMonth = new Map<string, TeamOverview['upcoming_certs']>()
  for (const c of data.upcoming_certs) {
    if (!c.valid_to) continue
    const d = new Date(c.valid_to)
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    byMonth.set(key, [...(byMonth.get(key) ?? []), c])
  }
  const teamLine = data.teams.map((r) => r.team).join(', ')

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5, mb: 3 }}>
      <Panel title={data.teams.length > 1 ? 'Ekiplerimden beklenenler' : 'Ekibimden beklenenler'}
             aside={<Typography variant="body2" color="text.secondary">
               {teamLine} · {t.domains} domain · {t.certificates} aktif sertifika
             </Typography>}>
        {todos.length === 0 ? (
          <Typography variant="body2" color="text.secondary">Şu an ekibinizden beklenen bir işlem yok. Tüm sertifikalar güncel.</Typography>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {todos.map((x) => <Todo key={x.text} n={x.n} tone={x.tone} text={x.text} onClick={x.go} />)}
          </Box>
        )}
      </Panel>

      {data.teams.length > 1 && (
        <Panel title="Ekiplerim" pad={false}>
          <TeamSummaryTable rows={data.teams} soonDays={data.expiring_soon_days} onOpen={(id) => navigate(`/teams/${id}`)} />
        </Panel>
      )}

      <Panel title="Yenileme takvimi (90 gün)"
             aside={<Typography variant="caption" color="text.secondary">Ekibimin sertifikaları, bitiş tarihine göre</Typography>}>
        {byMonth.size === 0 ? (
          <Typography variant="body2" color="text.secondary">Önümüzdeki 90 günde biten sertifika yok.</Typography>
        ) : (
          <Box sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: { xs: '1fr', md: 'repeat(3, 1fr)' } }}>
            {[...byMonth.entries()].map(([key, certs]) => (
              <Box key={key} sx={{ border: 1, borderColor: 'divider', borderRadius: '10px', p: 1.5 }}>
                <Typography sx={{ fontWeight: 650, mb: 0.5 }}>
                  {monthLabel(key)} <Typography component="span" color="text.secondary">· {certs.length}</Typography>
                </Typography>
                {certs.map((c) => (
                  <ButtonBase key={c.id} onClick={() => navigate(`/certificates?cert=${c.id}`)}
                              sx={{ width: '100%', justifyContent: 'flex-start', gap: 1, py: 0.75, borderTop: 1, borderColor: 'divider',
                                    textAlign: 'left', '&:hover': { color: 'primary.main' } }}>
                    <Typography variant="body2" sx={{ fontVariantNumeric: 'tabular-nums', color: 'text.secondary', flexShrink: 0 }}>
                      {new Date(c.valid_to!).toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit' })}
                    </Typography>
                    <Typography variant="body2" noWrap>{c.name}</Typography>
                  </ButtonBase>
                ))}
              </Box>
            ))}
          </Box>
        )}
      </Panel>
    </Box>
  )
}
