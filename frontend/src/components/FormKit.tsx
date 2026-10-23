import { Box, Button, Typography } from '@mui/material'
import type { ReactNode } from 'react'
import { CARD_SX, IconBadge } from './DetailCards'

/**
 * Pencere içi düzenleme formlarının ortak parçaları: alanlar konu başlıklı kartlarda toplanır,
 * Kaydet/Vazgeç her zaman görünen alt çubukta durur (uzun formda kaydırınca kaybolmaz).
 */

/** Başlıklı alan grubu (ör. "Sahiplik ve iletişim"). */
export function FormSection({ icon, title, hint, children, columns = 3 }: {
  icon?: ReactNode
  title: string
  hint?: string
  children: ReactNode
  columns?: 1 | 2 | 3
}) {
  return (
    <Box sx={{ ...CARD_SX, p: { xs: 2, md: 2.5 } }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, mb: 2 }}>
        {icon && <IconBadge size={30}>{icon}</IconBadge>}
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, lineHeight: 1.3 }}>{title}</Typography>
          {hint && <Typography variant="caption" color="text.secondary">{hint}</Typography>}
        </Box>
      </Box>
      <Box sx={{ display: 'grid', columnGap: 2, rowGap: 2.25, alignItems: 'start',
                 gridTemplateColumns: { xs: '1fr', sm: columns === 1 ? '1fr' : '1fr 1fr', md: `repeat(${columns}, minmax(0, 1fr))` } }}>
        {children}
      </Box>
    </Box>
  )
}

/** Formun altına yapışık işlem çubuğu: solda durum metni, sağda Vazgeç / Kaydet. */
export function EditFooter({ status, onCancel, onSave, saveLabel = 'Kaydet', saveDisabled, busy }: {
  status: ReactNode
  onCancel: () => void
  onSave: () => void
  saveLabel?: string
  saveDisabled?: boolean
  busy?: boolean
}) {
  return (
    <Box sx={(t) => ({
      position: 'sticky', bottom: -24, zIndex: 2, mt: 2.5, mx: { xs: -2, md: -3 }, mb: -3,
      px: { xs: 2, md: 3 }, py: 1.5, display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap',
      bgcolor: 'background.paper', borderTop: 1, borderColor: 'divider',
      boxShadow: `0 -6px 16px ${t.palette.mode === 'dark' ? 'rgba(0,0,0,0.35)' : 'rgba(16,24,40,0.06)'}`,
    })}>
      <Typography variant="body2" color="text.secondary" sx={{ flexGrow: 1, minWidth: 0 }}>{status}</Typography>
      <Button color="inherit" onClick={onCancel} disabled={busy} sx={{ color: 'text.secondary' }}>Vazgeç</Button>
      <Button variant="contained" disableElevation onClick={onSave} disabled={saveDisabled || busy}>{saveLabel}</Button>
    </Box>
  )
}
