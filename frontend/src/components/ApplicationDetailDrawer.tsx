import ArrowForwardIcon from '@mui/icons-material/ArrowForward'
import CloseIcon from '@mui/icons-material/Close'
import {
  Box, Chip, Divider, Drawer, IconButton, Paper, Skeleton, Stack, Tooltip, Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Application } from '../api/types'
import { MONO_FONT } from '../theme'
import SkiText from './SkiText'

interface Props {
  appId: number | null
  onClose: () => void
}

function Field({ label, value, mono }: { label: string; value?: string | null; mono?: boolean }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="body2"
                  sx={mono ? { fontFamily: MONO_FONT, fontSize: 12, wordBreak: 'break-all' }
                           : { wordBreak: 'break-word' }}>
        {value || '—'}
      </Typography>
    </Box>
  )
}

export default function ApplicationDetailDrawer({ appId, onClose }: Props) {
  const { data: app, isLoading } = useQuery<Application>({
    queryKey: ['application', appId],
    queryFn: async () => (await api.get(`/applications/${appId}`)).data,
    enabled: appId !== null,
  })

  return (
    <Drawer anchor="right" open={appId !== null} onClose={onClose}
            slotProps={{ paper: { sx: { width: { xs: '100%', sm: 560 } } } }}>
      <Box sx={{ p: 3 }}>
        {isLoading || !app ? (
          <Skeleton variant="rounded" height={500} />
        ) : (
          <Stack spacing={2}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="h6" sx={{ flexGrow: 1, wordBreak: 'break-word' }}>
                {app.app_name}
              </Typography>
              <Chip size="small" color={app.status ? 'success' : 'default'}
                    label={app.status ? 'Aktif' : 'Pasif'} />
              <Tooltip title="Kapat">
                <IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton>
              </Tooltip>
            </Box>

            <Stack direction="row" spacing={4}>
              <Field label="Sunucu" value={app.server_name} />
              <Field label="IP Adresi" value={app.ip_address} mono />
            </Stack>
            <Stack direction="row" spacing={4}>
              <Field label="DNS" value={app.dns} />
              <Field label="Uygulama Kullanıcısı" value={app.app_user} />
            </Stack>
            <Stack direction="row" spacing={4}>
              <Field label="SY Takımı" value={app.sy_team?.name} />
              <Field label="UG Takımı" value={app.ug_team?.name} />
            </Stack>
            <Field label="Bağlı Domain (server)" value={app.domain?.domain} />
            <Box>
              <Typography variant="caption" color="text.secondary">Etiketler</Typography>
              {(app.tags ?? []).length === 0 ? (
                <Typography variant="body2">—</Typography>
              ) : (
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
                  {(app.tags ?? []).map((t) => (
                    <Chip key={t.id} size="small" label={`${t.category}: ${t.name}`} variant="outlined"
                          sx={t.color ? { borderColor: t.color, color: t.color } : undefined} />
                  ))}
                </Box>
              )}
            </Box>
            <Divider />

            <Typography variant="overline" color="text.secondary">İşletim</Typography>
            <Field label="Config Path" value={app.conf_path} mono />
            <Field label="Log Path" value={app.log_path} mono />
            <Stack direction="row" spacing={4}>
              <Field label="Kontrol Yöntemi" value={app.control_method} />
              <Field label="Start/Stop Yöntemi" value={app.start_stop_method} />
            </Stack>
            <Field label="Gerekli Komutlar" value={app.required_commands} mono />
            <Field label="Servis Sağlayıcı İletişim" value={app.service_provider_contact} />
            <Field label="Bilgi" value={app.info} />
            <Field label="Notlar" value={app.notes} />
            <Divider />

            <Typography variant="overline" color="text.secondary">
              Dış Bağımlılıklar (client)
            </Typography>
            {(app.dependencies ?? []).length === 0 && (
              <Typography variant="body2" color="text.secondary">Dış bağımlılık tanımlı değil.</Typography>
            )}
            {(app.dependencies ?? []).map((d) => (
              <Paper key={d.id} variant="outlined" sx={{ p: 1, display: 'flex', gap: 1 }}>
                <ArrowForwardIcon fontSize="small" sx={{ color: '#ff9800', mt: 0.25 }} />
                <Box sx={{ minWidth: 0 }}>
                  <Typography variant="body2" sx={{ fontWeight: 600 }} noWrap>
                    {d.target_domain_name ?? `#${d.target_domain_id}`}
                  </Typography>
                  {d.client_cert_name && (
                    <>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                        mTLS: {d.client_cert_name}
                      </Typography>
                      <SkiText value={d.client_cert_ski} />
                    </>
                  )}
                  {d.note && (
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                      {d.note}
                    </Typography>
                  )}
                </Box>
              </Paper>
            ))}
          </Stack>
        )}
      </Box>
    </Drawer>
  )
}
