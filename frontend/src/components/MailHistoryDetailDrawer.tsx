import CloseIcon from '@mui/icons-material/Close'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import ReplayIcon from '@mui/icons-material/Replay'
import {
  Alert, Box, Button, Chip, Divider, Drawer, IconButton, Skeleton, Stack, Tab, Tabs, Tooltip, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import type { MailHistoryDetail } from '../api/types'
import { MONO_FONT, daysLeftColor, daysLeftLabel } from '../theme'
import { formatAuditTime, relativeTime } from '../utils/auditFormat'
import { MAIL_STATUS, MAIL_TYPE } from '../utils/mailFormat'

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>{label}</Typography>
      <Box sx={{ typography: 'body2', wordBreak: 'break-word' }}>{children}</Box>
    </Box>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700, lineHeight: 1.8 }}>{children}</Typography>
}

/** Kuyruğa alınma → teslim / başarısızlık zaman çizelgesi. */
function Timeline({ d }: { d: MailHistoryDetail }) {
  const steps: { label: string; at?: string | null; tone: string; note?: string }[] = []
  if (d.queued_at && d.delivered_at && d.queued_at === d.delivered_at) {
    steps.push({ label: 'Doğrudan gönderildi', at: d.delivered_at, tone: 'success.main' })
  } else {
    if (d.queued_at) steps.push({ label: 'Kuyruğa alındı', at: d.queued_at, tone: 'info.main' })
    if (d.status === 'sent') steps.push({ label: 'Teslim edildi', at: d.delivered_at, tone: 'success.main' })
    if (d.status === 'pending') steps.push({ label: 'Gönderim bekliyor', tone: 'warning.main',
                                             note: d.attempts ? `${d.attempts} deneme yapıldı` : 'Henüz denenmedi' })
    if (d.status === 'failed') steps.push({ label: 'Gönderilemedi', tone: 'error.main',
                                            note: d.attempts ? `${d.attempts} denemeden sonra vazgeçildi` : undefined })
  }
  return (
    <Stack spacing={0}>
      {steps.map((s, i) => (
        <Box key={i} sx={{ display: 'flex', gap: 1.25 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', pt: 0.6 }}>
            <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: s.tone, flexShrink: 0 }} />
            {i < steps.length - 1 && <Box sx={{ width: 2, flexGrow: 1, minHeight: 18, bgcolor: 'divider', my: 0.25 }} />}
          </Box>
          <Box sx={{ pb: i < steps.length - 1 ? 1 : 0 }}>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>{s.label}</Typography>
            <Typography variant="caption" color="text.secondary">
              {s.at ? `${formatAuditTime(s.at, true)} · ${relativeTime(s.at)}` : s.note}
              {s.at && s.note ? ` · ${s.note}` : ''}
            </Typography>
          </Box>
        </Box>
      ))}
    </Stack>
  )
}

export default function MailHistoryDetailDrawer({ item, onClose, onChanged, onOpenRecord }: {
  item: { source: string; id: number } | null
  onClose: () => void
  onChanged?: () => void
  onOpenRecord?: (kind: 'cert' | 'domain', id: number) => void
}) {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<'html' | 'text'>('html')
  const { data: d, isLoading } = useQuery<MailHistoryDetail>({
    queryKey: ['mail-history-detail', item?.source, item?.id],
    queryFn: async () => (await api.get(`/notifications/history/${item!.source}/${item!.id}`)).data,
    enabled: item !== null,
  })
  const retry = useMutation({
    mutationFn: async () => (await api.post(`/notifications/history/${item!.source}/${item!.id}/retry`)).data,
    onSuccess: () => {
      enqueueSnackbar('Mail yeniden kuyruğa alındı — kuyruk işi bir sonraki turda gönderecek', { variant: 'success' })
      queryClient.invalidateQueries({ queryKey: ['mail-history-detail', item?.source, item?.id] })
      onChanged?.()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const type = d ? MAIL_TYPE[d.mail_type] : undefined
  const record = d?.certificate_id && d.certificate_name ? { kind: 'cert' as const, id: d.certificate_id, label: d.certificate_name }
    : d?.domain_id && d.domain_name ? { kind: 'domain' as const, id: d.domain_id, label: d.domain_name } : null

  return (
    <Drawer anchor="right" open={item !== null} onClose={onClose}
            slotProps={{ paper: { sx: { width: { xs: '100%', sm: 680 } } } }}>
      <Box sx={{ p: 3 }}>
        {isLoading || !d ? (
          <Skeleton variant="rounded" height={500} />
        ) : (
          <Stack spacing={2.25}>
            {/* Başlık */}
            <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
              <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.25 }}>
                  <Box component="span" sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: type?.color }} />
                  <Typography variant="overline" color="text.secondary" sx={{ lineHeight: 1.6 }}>
                    {type?.label ?? d.mail_type}
                  </Typography>
                </Box>
                <Typography variant="h6" sx={{ wordBreak: 'break-word', lineHeight: 1.3 }}>
                  {d.subject || '(Konu yok)'}
                </Typography>
              </Box>
              <Chip size="small" color={MAIL_STATUS[d.status]?.color ?? 'default'}
                    label={MAIL_STATUS[d.status]?.label ?? d.status} />
              <Tooltip title="Kapat">
                <IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton>
              </Tooltip>
            </Box>

            {d.status === 'failed' && d.error && (
              <Alert severity="error" variant="outlined"
                     action={d.retryable ? (
                       <Button color="error" size="small" startIcon={<ReplayIcon />}
                               onClick={() => retry.mutate()} disabled={retry.isPending}>
                         Yeniden kuyruğa al
                       </Button>
                     ) : undefined}>
                <Box sx={{ fontFamily: MONO_FONT, fontSize: 12, wordBreak: 'break-word' }}>{d.error}</Box>
                {!d.retryable && (
                  <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 0.5 }}>
                    Bu mail hiç denenemediği (alıcı belirlenemediği) için yeniden kuyruğa alınamaz — hatayı giderin,
                    bir sonraki tarama yeniden üretir.
                  </Typography>
                )}
              </Alert>
            )}

            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr 1fr', sm: 'repeat(4, 1fr)' }, gap: 2,
                       p: 1.5, borderRadius: 1.5, bgcolor: 'background.default', border: '1px solid', borderColor: 'divider' }}>
              <Meta label="Sertifika / Domain">
                {record ? (
                  <Box>
                    <Box sx={{ fontWeight: 500 }}>{record.label}</Box>
                    <Typography variant="caption" color="text.secondary">{record.kind === 'cert' ? 'sertifika' : 'domain'}</Typography>
                  </Box>
                ) : '—'}
              </Meta>
              <Meta label="Kalan Gün">
                {d.days_left == null ? '—'
                  : <Chip size="small" color={daysLeftColor(d.days_left)} label={daysLeftLabel(d.days_left)} />}
              </Meta>
              <Meta label="Paydaş">{d.stakeholder || '—'}</Meta>
              <Meta label="Kanal">{d.channel === 'email' ? 'E-posta' : d.channel}</Meta>
            </Box>

            {record && onOpenRecord && (
              <Box>
                <Button size="small" variant="outlined" startIcon={<OpenInNewIcon />}
                        onClick={() => onOpenRecord(record.kind, record.id)}>
                  {record.kind === 'cert' ? 'Sertifikayı aç' : 'Domaini aç'}
                </Button>
              </Box>
            )}

            <Box>
              <SectionTitle>Alıcılar · {d.recipients.length}</SectionTitle>
              {d.recipients.length ? (
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                  {d.recipients.map((r) => <Chip key={r} size="small" variant="outlined" label={r} />)}
                </Box>
              ) : <Typography variant="body2" color="text.secondary">{d.recipient || '—'}</Typography>}
            </Box>

            <Box>
              <SectionTitle>Gönderim akışı</SectionTitle>
              <Timeline d={d} />
            </Box>

            <Divider />

            {d.body_html || d.body_text ? (
              <Stack spacing={1}>
                <Tabs value={d.body_html ? tab : 'text'} onChange={(_, v) => setTab(v)} sx={{ minHeight: 32 }}>
                  {d.body_html && <Tab value="html" label="Önizleme" sx={{ minHeight: 32, py: 0.5 }} />}
                  <Tab value="text" label="Düz Metin" sx={{ minHeight: 32, py: 0.5 }} />
                </Tabs>
                {tab === 'html' && d.body_html ? (
                  <Box component="iframe" title="Mail Önizleme" srcDoc={d.body_html}
                       sx={{ width: '100%', height: 480, border: '1px solid', borderColor: 'divider',
                             borderRadius: 1, bgcolor: '#fff' }} />
                ) : (
                  <Box component="pre"
                       sx={{ fontFamily: MONO_FONT, fontSize: 12, m: 0, p: 1.5, borderRadius: 1,
                             bgcolor: 'action.hover', maxHeight: 480, overflow: 'auto',
                             whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                    {d.body_text || '—'}
                  </Box>
                )}
              </Stack>
            ) : (
              <Typography variant="body2" color="text.secondary">
                Bu mail başarıyla gönderildiği için gövde metni saklanmıyor — yalnızca yukarıdaki
                özet bilgiler kayıtlıdır. Gövde yalnızca kuyrukta bekleyen/başarısız mailler için tutulur.
              </Typography>
            )}
            <Typography variant="caption" color="text.disabled">
              Kayıt: {d.source === 'queue' ? 'mail kuyruğu' : 'bildirim'} #{d.id}
            </Typography>
          </Stack>
        )}
      </Box>
    </Drawer>
  )
}
