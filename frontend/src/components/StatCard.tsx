import { Box, Paper, Typography } from '@mui/material'
import { alpha } from '@mui/material/styles'
import type { ReactNode } from 'react'

/** Kurumsal KPI kartı: solda tint'li ikon kutusu, kalın değer + büyük harf etiket. */
export default function StatCard({ icon, label, value, color, onClick }: {
  icon?: ReactNode
  label: string
  value: number | string
  color: string
  onClick?: () => void
}) {
  return (
    <Paper
      variant="outlined" onClick={onClick}
      sx={{
        p: 2.5, display: 'flex', alignItems: 'center', gap: 2, height: '100%',
        cursor: onClick ? 'pointer' : 'default',
        transition: 'border-color .15s ease, transform .15s ease, box-shadow .15s ease',
        ...(onClick && {
          '&:hover': {
            borderColor: color, transform: 'translateY(-2px)',
            boxShadow: `0 6px 20px ${alpha(color, 0.18)}`,
          },
        }),
      }}
    >
      {icon && (
        <Box sx={{ flexShrink: 0, width: 50, height: 50, borderRadius: 2.5, display: 'grid',
                   placeItems: 'center', color, bgcolor: alpha(color, 0.14) }}>
          {icon}
        </Box>
      )}
      <Box sx={{ minWidth: 0 }}>
        <Typography sx={{ fontWeight: 800, fontSize: 30, lineHeight: 1.05, letterSpacing: '-0.02em',
                          color: icon ? 'text.primary' : color }}>
          {value}
        </Typography>
        <Typography variant="caption" color="text.secondary"
                    sx={{ textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>
          {label}
        </Typography>
      </Box>
    </Paper>
  )
}
