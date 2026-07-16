import { Box, Chip, Grid, Paper, Skeleton, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@mui/material'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import BusinessIcon from '@mui/icons-material/Business'
import GroupsOutlinedIcon from '@mui/icons-material/GroupsOutlined'
import VerifiedIcon from '@mui/icons-material/Verified'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlineOutlined'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { DashboardData } from '../api/types'
import PageHeader from '../components/PageHeader'
import QueryError from '../components/QueryError'
import StatCard from '../components/StatCard'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { daysLeftColor } from '../theme'

const TILE_COLORS = ['#42a5f5', '#ffca28', '#ffa726', '#ef5350', '#ab47bc', '#26c6da', '#66bb6a', '#ec407a']

function SectionTitle({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <Typography variant="subtitle2" sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2.5,
                color: 'text.secondary', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
      {icon}{children}
    </Typography>
  )
}

export default function Dashboard() {
  useDocumentTitle('Anasayfa')
  const navigate = useNavigate()
  const { data, isLoading, isError, error, refetch } = useQuery<DashboardData>({
    queryKey: ['dashboard'],
    queryFn: async () => (await api.get('/dashboard')).data,
  })

  if (isError) {
    return (
      <Box>
        <PageHeader title="Anasayfa" subtitle="Sertifika ve domain durumuna genel bakış" />
        <QueryError error={error} onRetry={() => refetch()} />
      </Box>
    )
  }
  if (isLoading || !data) {
    return <Skeleton variant="rounded" height={480} />
  }

  return (
    <Box>
    <PageHeader title="Anasayfa" subtitle="Sertifika ve domain durumuna genel bakış" />
    <Grid container spacing={3}>
      <Grid size={{ xs: 12 }}>
        <Grid container spacing={2}>
          <Grid size={{ xs: 6, md: 3 }}>
            <StatCard icon={<BusinessIcon fontSize="large" />} label="Toplam Domain" value={data.total_domains} color="#42a5f5"
                      onClick={() => navigate('/domains')} />
          </Grid>
          <Grid size={{ xs: 6, md: 3 }}>
            <StatCard icon={<ErrorOutlineIcon fontSize="large" />} label="Süresi Dolmuş" value={data.expired_domains} color="#ef5350"
                      onClick={() => navigate('/domains')} />
          </Grid>
          <Grid size={{ xs: 6, md: 3 }}>
            <StatCard icon={<VerifiedIcon fontSize="large" />} label="Geçerli" value={data.valid_domains} color="#66bb6a"
                      onClick={() => navigate('/domains')} />
          </Grid>
          <Grid size={{ xs: 6, md: 3 }}>
            <StatCard icon={<VerifiedIcon fontSize="large" />} label="Toplam Sertifika" value={data.total_certificates} color="#ab47bc"
                      onClick={() => navigate('/certificates')} />
          </Grid>
        </Grid>
      </Grid>

      <Grid size={{ xs: 12, md: 5 }}>
        <Paper variant="outlined" sx={{ p: 3, height: '100%' }}>
          <SectionTitle icon={<GroupsOutlinedIcon fontSize="small" />}>SY Bazında Domain Adetleri</SectionTitle>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5 }}>
            {data.sy_domain_counts.length === 0 && (
              <Typography color="text.secondary">Henüz SY takımı atanmış domain yok</Typography>
            )}
            {data.sy_domain_counts.map((item, i) => (
              <Paper
                key={item.team}
                variant="outlined"
                onClick={() => navigate(`/domains?sy=${encodeURIComponent(item.team)}`)}
                title={`${item.team} domainlerini görüntüle`}
                sx={{
                  px: 2.5, py: 1.5, textAlign: 'center', minWidth: 84, cursor: 'pointer',
                  borderColor: TILE_COLORS[i % TILE_COLORS.length],
                  boxShadow: `0 0 12px ${TILE_COLORS[i % TILE_COLORS.length]}33`,
                  '&:hover': { bgcolor: 'action.hover' },
                }}
              >
                <Typography variant="h5" sx={{ color: TILE_COLORS[i % TILE_COLORS.length] }}>
                  {item.count}
                </Typography>
                <Typography variant="caption" color="text.secondary">{item.team}</Typography>
              </Paper>
            ))}
          </Box>
        </Paper>
      </Grid>

      <Grid size={{ xs: 12, md: 7 }}>
        <Paper variant="outlined" sx={{ p: 3 }}>
          <SectionTitle icon={<WarningAmberIcon fontSize="small" sx={{ color: 'warning.main' }} />}>
            Bitiş Tarihi Yaklaşan Sertifikalar
          </SectionTitle>
          <TableContainer sx={{ overflowX: 'auto' }}>
          <Table size="small" sx={{ minWidth: 620 }}>
            <TableHead>
              <TableRow>
                <TableCell>Sertifika</TableCell>
                <TableCell>SerialNumber</TableCell>
                <TableCell>Domainler</TableCell>
                <TableCell>SY</TableCell>
                <TableCell align="right">Bitiş Tarihi</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {data.expiring_certificates.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} align="center" sx={{ py: 5, color: 'text.secondary' }}>
                    <VerifiedIcon sx={{ color: 'success.main', mb: 0.5 }} />
                    <Typography variant="body2">Yaklaşan bitiş yok — tüm sertifikalar güncel.</Typography>
                  </TableCell>
                </TableRow>
              )}
              {data.expiring_certificates.map((cert) => (
                <TableRow key={cert.certificate_id} hover>
                  <TableCell sx={{ fontWeight: 600, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                             title={cert.name}>
                    {cert.name}
                  </TableCell>
                  <TableCell title={cert.serial_number ?? ''}
                             sx={{ fontFamily: 'monospace', fontSize: 12, maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {cert.serial_number}
                  </TableCell>
                  <TableCell title={cert.domains || ''}
                             sx={{ maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {cert.domains || '—'}
                  </TableCell>
                  <TableCell title={cert.sy_teams || ''}
                             sx={{ maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {cert.sy_teams || '—'}
                  </TableCell>
                  <TableCell align="right">
                    <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 1, whiteSpace: 'nowrap' }}>
                      {cert.valid_to ? new Date(cert.valid_to).toLocaleDateString('tr-TR') : '—'}
                      {cert.days_left !== null && cert.days_left !== undefined && cert.days_left <= 30 && (
                        <Chip size="small" color={daysLeftColor(cert.days_left)}
                              label={cert.days_left < 0 ? 'Doldu' : `${cert.days_left}g`} />
                      )}
                    </Box>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          </TableContainer>
        </Paper>
      </Grid>
    </Grid>
    </Box>
  )
}
