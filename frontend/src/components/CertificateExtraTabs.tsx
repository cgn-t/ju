// Sertifika detayının 'Mailler' ve 'Etkilenenler' sekmeleri (v3.9.9).
import AppsIcon from '@mui/icons-material/Apps'
import LanguageIcon from '@mui/icons-material/Language'
import MailOutlineIcon from '@mui/icons-material/MailOutlined'
import {
  Box, Skeleton, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Tooltip, Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { CertificateImpact, MailHistoryEntry } from '../api/types'
import { MAIL_STATUS, MAIL_TYPE } from '../utils/mailFormat'
import { CARD_SX, fmtDate, IconBadge, SectionBox, StatusPill } from './DetailCards'
import { EmptyState } from './ListKit'

const fmtDay = (v?: string | null) => (v ? new Date(v).toLocaleDateString('tr-TR', { day: '2-digit', month: 'short', year: 'numeric' }) : '—')

/** Bu sertifika için gönderilen (ve gönderilemeyen) uyarı mailleri, en yeni önce. */
export function CertificateMailsTab({ certId }: { certId: number }) {
  const { data, isLoading } = useQuery<MailHistoryEntry[]>({
    queryKey: ['certificate', certId, 'mails'],
    queryFn: async () => (await api.get(`/certificates/${certId}/mails`)).data,
  })
  if (isLoading || !data) return <Skeleton variant="rounded" height={260} />
  if (!data.length) {
    return (
      <Box sx={CARD_SX}>
        <EmptyState title="Bu sertifika için henüz mail gönderilmedi"
                    hint="Uyarı mailleri bitiş tarihine Bildirim Gün Sayısı kadar kala başlar. Kimlere gideceği Etkilenenler sekmesinde." />
      </Box>
    )
  }
  const failed = data.filter((m) => m.status === 'failed').length
  return (
    <Stack spacing={2}>
      <Typography variant="body2" color="text.secondary">
        Son {data.length} mail{failed ? ` · ${failed} tanesi gönderilemedi` : ''}. Tarihler İstanbul saatidir.
      </Typography>
      <Box sx={{ ...CARD_SX, overflow: 'hidden' }}>
        <TableContainer sx={{ overflowX: 'auto' }}>
          <Table size="small" sx={{ minWidth: 640 }}>
            <TableHead>
              <TableRow>
                <TableCell>Tarih</TableCell>
                <TableCell>Kime</TableCell>
                <TableCell>Tür</TableCell>
                <TableCell align="right">Kalan</TableCell>
                <TableCell>Durum</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {data.map((m) => {
                const st = MAIL_STATUS[m.status]
                return (
                  <TableRow key={`${m.source}-${m.id}`}>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{fmtDate(m.sent_at)}</TableCell>
                    <TableCell sx={{ wordBreak: 'break-word' }}>
                      {(m.recipients.length ? m.recipients : [m.recipient ?? '—']).join(', ')}
                      {m.stakeholder && <Typography variant="caption" color="text.secondary" component="div">{m.stakeholder}</Typography>}
                    </TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{MAIL_TYPE[m.mail_type]?.label ?? '—'}</TableCell>
                    <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                      {m.days_left === null || m.days_left === undefined ? '—' : m.days_left < 0 ? `${-m.days_left} gün geçti` : `${m.days_left} gün`}
                    </TableCell>
                    <TableCell>
                      <Tooltip title={m.error ?? ''}>
                        <span><StatusPill size="small" tone={st.color} label={st.label} /></span>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </Box>
    </Stack>
  )
}

/** Sertifika biterse etkilenecek domainler, uygulamalar ve uyarı alacak kişiler. */
export function CertificateImpactTab({ certId, onOpenDomain }: { certId: number; onOpenDomain: (id: number) => void }) {
  const { data, isLoading } = useQuery<CertificateImpact>({
    queryKey: ['certificate', certId, 'impact'],
    queryFn: async () => (await api.get(`/certificates/${certId}/impact`)).data,
  })
  if (isLoading || !data) return <Skeleton variant="rounded" height={320} />
  return (
    <Stack spacing={2}>
      <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' } }}>
        <SectionBox title={`Domainler (${data.domains.length})`}>
          {data.domains.length === 0 ? (
            <Typography variant="body2" color="text.secondary">Bu sertifika hiçbir domain'e bağlı değil.</Typography>
          ) : data.domains.map((d, i) => (
            <Box key={`${d.domain_id}-${d.mapping_type}`} onClick={() => onOpenDomain(d.domain_id)}
                 sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 1, cursor: 'pointer',
                       borderTop: i ? 1 : 0, borderColor: 'divider', '&:hover': { color: 'primary.main' } }}>
              <IconBadge size={30}><LanguageIcon /></IconBadge>
              <Box sx={{ minWidth: 0, flexGrow: 1 }}>
                <Typography variant="body2" noWrap sx={{ fontWeight: 600 }}>{d.domain}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {d.mapping_type === 'server' ? 'Server' : 'Trusted'}{d.team ? ` · ${d.team}` : ' · ekibi yok'}
                </Typography>
              </Box>
            </Box>
          ))}
        </SectionBox>
        <SectionBox title={`Uygulamalar (${data.applications.length})`}>
          {data.applications.length === 0 ? (
            <Typography variant="body2" color="text.secondary">Bu sertifikayı kullanan uygulama kaydı yok.</Typography>
          ) : data.applications.map((a, i) => (
            <Box key={`${a.app_id}-${a.relation}`}
                 sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 1, borderTop: i ? 1 : 0, borderColor: 'divider' }}>
              <IconBadge size={30}><AppsIcon /></IconBadge>
              <Box sx={{ minWidth: 0, flexGrow: 1 }}>
                <Typography variant="body2" noWrap sx={{ fontWeight: 600 }}>
                  {a.app_name}{!a.active && <Typography component="span" variant="caption" color="text.secondary"> (pasif)</Typography>}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {a.relation}{a.via ? ` · ${a.via}` : ''}{a.team ? ` · ${a.team}` : ''}
                </Typography>
              </Box>
            </Box>
          ))}
        </SectionBox>
      </Box>

      <SectionBox title={`Uyarı maili alacaklar (${data.recipients.length})`}>
        {!data.mail_enabled && (
          <Typography variant="body2" color="warning.main" sx={{ mb: 1 }}>
            Mail gönderimi Ayarlar'da kapalı; açılınca bu kişilere gider.
          </Typography>
        )}
        {data.fallback && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Bu sertifikanın kendi alıcısı yok (sahip ekip, domain veya uygulama sahibi). Uyarılar yedek adrese gider.
          </Typography>
        )}
        {data.recipients.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            Uyarı alacak kimse yok ve yedek adres tanımlı değil. Bu sertifika için mail gitmez.
          </Typography>
        ) : data.recipients.map((r, i) => (
          <Box key={r.label + i} sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5, py: 1.25, borderTop: i ? 1 : 0, borderColor: 'divider' }}>
            <IconBadge size={30} tone={data.fallback ? 'warning' : 'info'}><MailOutlineIcon /></IconBadge>
            <Box sx={{ minWidth: 0, flexGrow: 1 }}>
              <Typography variant="body2" sx={{ fontWeight: 600, wordBreak: 'break-word' }}>{r.emails.join(', ')}</Typography>
              <Typography variant="caption" color="text.secondary" component="div">{r.label} · {r.reasons.join(' · ')}</Typography>
            </Box>
            <Box sx={{ textAlign: 'right', flexShrink: 0 }}>
              <Typography variant="caption" color="text.secondary" component="div">Uyarı başlangıcı</Typography>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>{fmtDay(r.starts_on)}</Typography>
              <Typography variant="caption" color="text.secondary">bitişten {r.effective_days} gün önce</Typography>
            </Box>
          </Box>
        ))}
      </SectionBox>
    </Stack>
  )
}
