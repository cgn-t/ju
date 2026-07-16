import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import { Box, IconButton, Tooltip, Typography } from '@mui/material'
import { useSnackbar } from 'notistack'
import { MONO_FONT } from '../theme'

interface Props {
  value?: string | null
  sx?: object
}

/** SubjectKeyIdentifier değeri: etiketsiz, mono; yanındaki minik kutuya
 *  tıklanınca tam değer panoya kopyalanır. */
export default function SkiText({ value, sx }: Props) {
  const { enqueueSnackbar } = useSnackbar()
  if (!value) {
    return <Typography variant="caption" color="text.secondary" sx={sx}>—</Typography>
  }
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.25, minWidth: 0, ...sx }}>
      <Tooltip title={value}>
        <Typography variant="caption" color="text.secondary" noWrap
                    sx={{ fontFamily: MONO_FONT, fontSize: 10.5, minWidth: 0 }}>
          {value}
        </Typography>
      </Tooltip>
      <Tooltip title="SKI'yi kopyala">
        <IconButton
          size="small" aria-label="SKI'yi kopyala"
          onClick={(e) => {
            e.stopPropagation()
            navigator.clipboard.writeText(value)
            enqueueSnackbar('SKI panoya kopyalandı', { variant: 'success' })
          }}
          sx={{ p: 0.25, flexShrink: 0, color: 'text.disabled',
                '&:hover': { color: 'text.primary' } }}>
          <ContentCopyIcon sx={{ fontSize: 12 }} />
        </IconButton>
      </Tooltip>
    </Box>
  )
}
