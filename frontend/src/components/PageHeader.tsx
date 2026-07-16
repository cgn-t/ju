import { Box, Typography } from '@mui/material'
import type { ReactNode } from 'react'

interface Props {
  title: string
  subtitle?: string
  actions?: ReactNode
}

/** Her sayfanın üstünde tutarlı başlık şeridi: sol tarafta başlık + açıklama, sağda aksiyonlar. */
export default function PageHeader({ title, subtitle, actions }: Props) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between',
               gap: 2, mb: 3, pb: 2, borderBottom: 1, borderColor: 'divider', flexWrap: 'wrap' }}>
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="h5" sx={{ display: 'flex', alignItems: 'center', gap: 1.25 }}>
          <Box component="span" sx={{ width: 4, height: 22, borderRadius: 1, bgcolor: 'primary.main', flexShrink: 0 }} />
          {title}
        </Typography>
        {subtitle && (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, ml: 2.5 }}>{subtitle}</Typography>
        )}
      </Box>
      {actions && <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>{actions}</Box>}
    </Box>
  )
}
