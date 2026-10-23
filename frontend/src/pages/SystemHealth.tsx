import { Box, Skeleton, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { HealthJob, SystemHealth as Health } from '../api/types'
import { fmtDate, StatusPill, type Tone } from '../components/DetailCards'
import PageHeader from '../components/PageHeader'
import QueryError from '../components/QueryError'
import { Panel } from '../components/TeamSummaryKit'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

function jobPill(j: HealthJob): { tone: Tone; label: string } {
  if (!j.enabled) return { tone: 'default', label: 'Kapalı' }
  if (!j.status) return { tone: 'default', label: 'Henüz çalışmadı' }
  return j.status === 'error' ? { tone: 'error', label: 'Hata' } : { tone: 'success', label: 'Başarılı' }
}

function Line({ label, value, tone, onClick }: { label: ReactNode; value: ReactNode; tone?: Tone; onClick?: () => void }) {
  return (
    <Box onClick={onClick}
         sx={(t) => ({ display: 'flex', justifyContent: 'space-between', gap: 2, py: 0.9, borderTop: 1, borderColor: 'divider',
                       '&:first-of-type': { borderTop: 0 }, cursor: onClick ? 'pointer' : 'default',
                       '&:hover': onClick ? { color: 'primary.main' } : undefined,
                       color: tone && tone !== 'default' ? (t.palette.mode === 'dark' ? t.palette[tone].light : t.palette[tone].dark) : undefined })}>
      <Typography variant="body2" sx={{ color: 'inherit' }}>{label}</Typography>
      <Typography variant="body2" sx={{ fontWeight: 650, color: 'inherit', textAlign: 'right' }}>{value}</Typography>
    </Box>
  )
}

/** Sistem Sağlığı (admin): otomatik işler, mail gönderimi, eksik bilgiler, bağlantılar. */
export default function SystemHealth() {
  useDocumentTitle('Sistem Sağlığı')
  const navigate = useNavigate()
  const { data, isLoading, isError, error, refetch } = useQuery<Health>({
    queryKey: ['system', 'health'],
    queryFn: async () => (await api.get('/system/health')).data,
  })
  const header = <PageHeader title="Sistem Sağlığı" subtitle="Otomatik işler, mail gönderimi ve bağlantılar tek bakışta" />
  if (isError) return <Box>{header}<QueryError error={error} onRetry={() => refetch()} /></Box>
  if (isLoading || !data) return <Box>{header}<Skeleton variant="rounded" height={520} /></Box>

  const m = data.mail_week
  const miss = data.missing
  const c = data.connections
  const onOff = (on: boolean, text?: string | null) => (
    <StatusPill size="small" tone={on ? 'success' : 'default'} label={on ? (text ? `Açık · ${text}` : 'Açık') : 'Kapalı'} />
  )
  return (
    <Box>
      {header}
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
        <Panel title="Otomatik işler" pad={false}>
          <TableContainer sx={{ overflowX: 'auto' }}>
            <Table size="small" sx={{ minWidth: 820 }}>
              <TableHead>
                <TableRow>
                  <TableCell>İş</TableCell>
                  <TableCell>Son çalışma</TableCell>
                  <TableCell>Sonuç</TableCell>
                  <TableCell>Özet</TableCell>
                  <TableCell>Sonraki</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data.jobs.map((j) => {
                  const p = jobPill(j)
                  return (
                    <TableRow key={j.id}>
                      <TableCell sx={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{j.label}</TableCell>
                      <TableCell sx={{ whiteSpace: 'nowrap' }}>
                        {j.last_run_at ? fmtDate(j.last_run_at) : '—'}
                        {j.manual && <Typography variant="caption" color="text.secondary"> (elle)</Typography>}
                      </TableCell>
                      <TableCell><StatusPill size="small" tone={p.tone} label={p.label} /></TableCell>
                      <TableCell sx={{ color: 'text.secondary' }}>
                        {j.enabled ? (j.summary ?? '—') : 'Ayarlar\'da kapalı'}
                        {j.duration_s ? <Typography variant="caption" color="text.disabled"> · {j.duration_s} sn</Typography> : null}
                      </TableCell>
                      <TableCell sx={{ whiteSpace: 'nowrap' }}>{j.next_run_at ? fmtDate(j.next_run_at) : '—'}</TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </TableContainer>
        </Panel>

        <Box sx={{ display: 'grid', gap: 2.5, gridTemplateColumns: { xs: '1fr', md: 'repeat(3, 1fr)' } }}>
          <Panel title="Mail gönderimi (son 7 gün)">
            <Line label="Gönderildi" value={m.sent} />
            <Line label="Gönderilemedi" value={m.failed} tone={m.failed ? 'error' : undefined} />
            <Line label="Reddedilen adres" value={m.refused} tone={m.refused ? 'warning' : undefined} />
            <Line label="Yedek adrese giden" value={m.fallback} />
            <Line label="Kuyrukta bekleyen" value={m.pending} />
            <Line label={<Typography variant="body2" color="primary">Mail geçmişini aç</Typography>} value=""
                  onClick={() => navigate('/settings?tab=mail-history')} />
          </Panel>
          <Panel title="Eksik bilgili kayıtlar">
            <Line label="Ekibi olmayan domain" value={miss.domains_without_team} tone={miss.domains_without_team ? 'warning' : undefined} />
            <Line label="Mail alıcısı olmayan sertifika" value={miss.certs_without_recipient} tone={miss.certs_without_recipient ? 'warning' : undefined} />
            <Line label="PEM'i olmayan sertifika" value={miss.certs_without_pem} />
            <Line label="Ekibi olmayan uygulama" value={miss.apps_without_team} />
            <Line label="Bildirim maili olmayan ekip" value={miss.teams_without_email} tone={miss.teams_without_email ? 'warning' : undefined} />
          </Panel>
          <Panel title="Bağlantılar">
            <Line label="Mail sunucusu (SMTP)" value={onOff(c.smtp.enabled, c.smtp.host)} />
            <Line label="Mail kuyruğu" value={onOff(c.smtp.queue_enabled)} />
            <Line label="Yedek adres" value={c.smtp.fallback_address || '—'} />
            <Line label="LDAP / AD" value={onOff(c.ldap.enabled, c.ldap.server)} />
            <Line label="Veritabanı" value={<StatusPill size="small" tone="success" label="Çalışıyor" />} />
            <Line label="Uygulama sürümü" value={c.version} />
          </Panel>
        </Box>
        <Typography variant="caption" color="text.secondary">
          Son çalışma bilgisi denetim kaydındaki iş özetlerinden okunur; kapalı işler çalışmaz. Bağlantılar bu sayfada test edilmez, Ayarlar'daki test butonları kullanılır.
        </Typography>
      </Box>
    </Box>
  )
}
