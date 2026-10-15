import { Box, Typography } from '@mui/material'
import type { AuditMeta } from '../api/types'

/**
 * Audit Log işlem göstergesi. Çip yerine RENKLİ NOKTA + etiket: değişken genişlikli
 * çipler kolonda düzensiz görünür; nokta sabit hizalı kalır.
 */

const TONE_COLOR: Record<string, string> = {
  success: 'success.main', info: 'info.main', error: 'error.main', warning: 'warning.main',
}

export default function ActionDot({ action, meta, withLabel = false }: {
  action: string; meta?: AuditMeta; withLabel?: boolean
}) {
  const tone = meta?.action_tone[action]
  const dot = (
    <Box component="span" sx={{
      width: 8, height: 8, borderRadius: '50%', flexShrink: 0, display: 'inline-block',
      bgcolor: tone ? TONE_COLOR[tone] : 'text.disabled',
    }} />
  )
  if (!withLabel) return dot
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0 }}>
      {dot}
      <Typography variant="body2" noWrap sx={{ fontWeight: 500 }}>{meta?.actions[action] ?? action}</Typography>
    </Box>
  )
}
