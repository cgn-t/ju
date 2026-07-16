import CloseIcon from '@mui/icons-material/Close'
import LinkIcon from '@mui/icons-material/Link'
import {
  Box, Chip, Divider, Drawer, IconButton, Skeleton, Stack, Tooltip, Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { DiscoveredCertificate, DiscoveryStatus } from '../api/types'
import { MONO_FONT, daysLeftColor, daysLeftLabel } from '../theme'

const STATUS: Record<DiscoveryStatus, { label: string; color: 'warning' | 'success' | 'info' | 'default' }> = {
  new: { label: 'Bilinmeyen (shadow)', color: 'warning' },
  in_inventory: { label: 'Envanterde', color: 'success' },
  adopted: { label: 'Envantere Alındı', color: 'info' },
  ignored: { label: 'Yok sayıldı', color: 'default' },
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

export default function DiscoveredCertificateDetailDrawer({ findingId, onClose }: {
  findingId: number | null
  onClose: () => void
}) {
  const { data: f, isLoading } = useQuery<DiscoveredCertificate>({
    queryKey: ['discovered-certificate', findingId],
    queryFn: async () => (await api.get(`/discovery/findings/${findingId}`)).data,
    enabled: findingId !== null,
  })

  return (
    <Drawer anchor="right" open={findingId !== null} onClose={onClose}
            slotProps={{ paper: { sx: { width: { xs: '100%', sm: 560 } } } }}>
      <Box sx={{ p: 3 }}>
        {isLoading || !f ? (
          <Skeleton variant="rounded" height={500} />
        ) : (
          <Stack spacing={2}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="h6" sx={{ flexGrow: 1, wordBreak: 'break-word' }}>
                {f.name || '(CN yok)'}
              </Typography>
              <Chip size="small" variant="outlined" color={f.origin === 'ct' ? 'secondary' : 'default'}
                    label={f.origin === 'ct' ? 'CT Log' : 'Ağ'} />
              <Chip size="small" color={STATUS[f.status].color} label={STATUS[f.status].label} />
              <Tooltip title="Kapat">
                <IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton>
              </Tooltip>
            </Box>

            <Stack direction="row" spacing={4}>
              <Field label={f.origin === 'ct' ? 'Domain (CT)' : 'Endpoint'}
                     value={f.origin === 'ct' ? f.host : `${f.host}:${f.port}`} mono />
              <Box>
                <Typography variant="caption" color="text.secondary">Kalan Süre</Typography>
                <Box><Chip size="small" color={daysLeftColor(f.days_left)} label={daysLeftLabel(f.days_left)} /></Box>
              </Box>
            </Stack>

            {f.origin === 'ct' && f.crtsh_id && (
              <Typography variant="body2">
                crt.sh kaydı:{' '}
                <a href={`https://crt.sh/?id=${f.crtsh_id}`} target="_blank" rel="noopener noreferrer">
                  #{f.crtsh_id}
                </a>
              </Typography>
            )}

            {f.sy_team_name && (
              <Field label="SY Ekip (envantere alınca Oluşturan olur)" value={f.sy_team_name} />
            )}
            {f.matched_certificate_id != null && (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                <LinkIcon fontSize="small" color="success" />
                <Typography variant="body2">
                  Envanterdeki kayıt: <b>{f.matched_certificate_name}</b> (#{f.matched_certificate_id})
                </Typography>
              </Box>
            )}
            <Divider />

            <Field label="Subject" value={f.subject} mono />
            <Field label="Issuer (CA)" value={f.issuer} mono />
            <Field label="SAN" value={f.san} mono />
            <Stack direction="row" spacing={4}>
              <Field label="Seri No" value={f.serial_number} mono />
              <Field label="Bitiş" value={f.valid_to ? new Date(f.valid_to).toLocaleString('tr-TR') : null} />
            </Stack>
            <Field label="SHA-256 Fingerprint" value={f.fingerprint_sha256} mono />
            <Stack direction="row" spacing={4}>
              <Field label="İlk Görülme" value={new Date(f.first_seen_at).toLocaleString('tr-TR')} />
              <Field label="Son Görülme" value={new Date(f.last_seen_at).toLocaleString('tr-TR')} />
            </Stack>
            <Divider />

            <Box>
              <Typography variant="caption" color="text.secondary">Sunulan PEM</Typography>
              <Box component="pre"
                   sx={{ fontFamily: MONO_FONT, fontSize: 11, m: 0, mt: 0.5, p: 1.5, borderRadius: 1,
                         bgcolor: 'action.hover', maxHeight: 240, overflow: 'auto', whiteSpace: 'pre-wrap',
                         wordBreak: 'break-all' }}>
                {f.pem_certificate || '—'}
              </Box>
            </Box>
          </Stack>
        )}
      </Box>
    </Drawer>
  )
}
