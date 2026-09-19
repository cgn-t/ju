import CloseIcon from '@mui/icons-material/Close'
import {
  Box, Chip, Divider, Drawer, IconButton, Skeleton, Stack, Tab, Tabs, Tooltip, Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import type { MailHistoryDetail } from '../api/types'
import { MONO_FONT, daysLeftColor, daysLeftLabel } from '../theme'

const STATUS: Record<string, { label: string; color: 'success' | 'warning' | 'error' | 'default' }> = {
  sent: { label: 'Gönderildi', color: 'success' },
  pending: { label: 'Kuyrukta', color: 'warning' },
  failed: { label: 'Başarısız', color: 'error' },
}

function Field({ label, value, mono }: { label: string; value?: string | null; mono?: boolean }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="body2"
                  sx={mono ? { fontFamily: MONO_FONT, fontSize: 12, wordBreak: 'break-word' }
                           : { wordBreak: 'break-word' }}>
        {value || '—'}
      </Typography>
    </Box>
  )
}

export default function MailHistoryDetailDrawer({ item, onClose }: {
  item: { source: string; id: number } | null
  onClose: () => void
}) {
  const [tab, setTab] = useState<'html' | 'text'>('html')
  const { data: d, isLoading } = useQuery<MailHistoryDetail>({
    queryKey: ['mail-history-detail', item?.source, item?.id],
    queryFn: async () => (await api.get(`/notifications/history/${item!.source}/${item!.id}`)).data,
    enabled: item !== null,
  })

  return (
    <Drawer anchor="right" open={item !== null} onClose={onClose}
            slotProps={{ paper: { sx: { width: { xs: '100%', sm: 640 } } } }}>
      <Box sx={{ p: 3 }}>
        {isLoading || !d ? (
          <Skeleton variant="rounded" height={500} />
        ) : (
          <Stack spacing={2}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="h6" sx={{ flexGrow: 1, wordBreak: 'break-word' }}>
                {d.subject || '(Konu yok)'}
              </Typography>
              <Chip size="small" color={STATUS[d.status]?.color ?? 'default'}
                    label={STATUS[d.status]?.label ?? d.status} />
              <Tooltip title="Kapat">
                <IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton>
              </Tooltip>
            </Box>

            <Stack direction="row" spacing={4} sx={{ flexWrap: 'wrap' }}>
              {d.queued_at && d.delivered_at && d.queued_at !== d.delivered_at ? (
                <>
                  <Field label="Kuyruğa Alınma" value={new Date(d.queued_at).toLocaleString('tr-TR')} />
                  <Field label="Gerçek Gönderim" value={new Date(d.delivered_at).toLocaleString('tr-TR')} />
                </>
              ) : d.delivered_at ? (
                <Field label="Gönderim Tarihi" value={new Date(d.delivered_at).toLocaleString('tr-TR')} />
              ) : d.queued_at ? (
                <>
                  <Field label="Kuyruğa Alınma" value={new Date(d.queued_at).toLocaleString('tr-TR')} />
                  <Field label="Gerçek Gönderim" value="Henüz gönderilmedi" />
                </>
              ) : (
                <Field label="Tarih" value={d.sent_at ? new Date(d.sent_at).toLocaleString('tr-TR') : null} />
              )}
              {d.days_left != null && (
                <Box>
                  <Typography variant="caption" color="text.secondary">Kalan Gün</Typography>
                  <Box><Chip size="small" color={daysLeftColor(d.days_left)} label={daysLeftLabel(d.days_left)} /></Box>
                </Box>
              )}
              <Field label="Kanal" value={d.channel} />
            </Stack>

            <Field label="Alıcı" value={d.recipient} mono />
            <Field label="Sertifika / Domain"
                   value={d.certificate_name || (d.domain_name ? `${d.domain_name} (domain)` : null)} />
            {d.error && <Field label="Hata" value={d.error} mono />}
            {d.attempts != null && <Field label="Deneme Sayısı" value={String(d.attempts)} />}

            <Divider />

            {d.body_html || d.body_text ? (
              <Stack spacing={1}>
                <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ minHeight: 32 }}>
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
          </Stack>
        )}
      </Box>
    </Drawer>
  )
}
