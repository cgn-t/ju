import AccessTimeIcon from '@mui/icons-material/AccessTime'
import CheckIcon from '@mui/icons-material/Check'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import {
  Alert, Box, Button, Divider, MenuItem, MenuList, Popover, Stack, TextField, Typography,
} from '@mui/material'
import { useState } from 'react'
import {
  formatLocalInput, QUICK_RANGES, TIME_PRESETS, toLocalInput, type TimePreset,
} from '../utils/auditFormat'

/**
 * Grafana tarzı zaman aralığı seçici: düğme seçili aralığı gösterir; açılan panelin solunda
 * MUTLAK aralık (başlangıç/bitiş, saatiyle) + "Uygula", sağında HIZLI aralıklar.
 * Mutlak değerler datetime-local biçimindedir (yerel = İstanbul saati).
 */
export default function TimeRangePicker({ preset, from, to, onChange }: {
  preset: TimePreset
  from: string
  to: string
  onChange: (preset: TimePreset, from?: string, to?: string) => void
}) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const [draftFrom, setDraftFrom] = useState('')
  const [draftTo, setDraftTo] = useState('')

  const open = (el: HTMLElement) => {
    // Panel açılırken mutlak alanları mevcut seçime göre doldur (özel değilse: son 24 saat)
    const now = new Date()
    setDraftFrom(preset === 'custom' && from ? from : toLocalInput(new Date(now.getTime() - 24 * 3600e3)))
    setDraftTo(preset === 'custom' && to ? to : toLocalInput(now))
    setAnchor(el)
  }
  const close = () => setAnchor(null)

  const invalid = !!draftFrom && !!draftTo && draftFrom > draftTo
  const label = preset === 'custom'
    ? (from || to ? `${from ? formatLocalInput(from) : '…'}  →  ${to ? formatLocalInput(to) : 'şimdi'}` : 'Özel aralık')
    : TIME_PRESETS.find((p) => p.value === preset)?.label ?? 'Son 1000 kayıt'

  const Option = ({ value, text }: { value: TimePreset; text: string }) => (
    <MenuItem selected={preset === value} dense sx={{ gap: 1 }}
              onClick={() => { onChange(value); close() }}>
      <CheckIcon sx={{ fontSize: 16, color: 'primary.main', visibility: preset === value ? 'visible' : 'hidden' }} />
      {text}
    </MenuItem>
  )

  return (
    <>
      <Button variant="outlined" color={preset === 'all' ? 'inherit' : 'primary'}
              startIcon={<AccessTimeIcon />} endIcon={<ExpandMoreIcon />}
              onClick={(e) => open(e.currentTarget)}
              sx={{ textTransform: 'none', fontWeight: 500, whiteSpace: 'nowrap', height: 40,
                    borderColor: preset === 'all' ? 'divider' : undefined,
                    fontVariantNumeric: 'tabular-nums' }}>
        {label}
      </Button>
      <Popover open={!!anchor} anchorEl={anchor} onClose={close}
               anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
               transformOrigin={{ vertical: 'top', horizontal: 'left' }}
               slotProps={{ paper: { sx: { mt: 0.5, borderRadius: 2, border: '1px solid', borderColor: 'divider', boxShadow: 6 } } }}>
        <Box sx={{ display: 'flex', flexDirection: { xs: 'column', sm: 'row' } }}>
          {/* Mutlak aralık */}
          <Box sx={{ p: 2, width: 300 }}>
            <Typography variant="subtitle2" sx={{ mb: 1.5 }}>Mutlak zaman aralığı</Typography>
            <Stack spacing={1.5}>
              <TextField size="small" type="datetime-local" label="Başlangıç" value={draftFrom}
                         onChange={(e) => setDraftFrom(e.target.value)}
                         slotProps={{ inputLabel: { shrink: true } }} />
              <TextField size="small" type="datetime-local" label="Bitiş" value={draftTo}
                         onChange={(e) => setDraftTo(e.target.value)}
                         helperText="Boş bırakılırsa: şimdi"
                         slotProps={{ inputLabel: { shrink: true } }} />
              {invalid && <Alert severity="warning" sx={{ py: 0 }}>Başlangıç, bitişten sonra olamaz.</Alert>}
              <Button variant="contained" disabled={!draftFrom || invalid}
                      onClick={() => { onChange('custom', draftFrom, draftTo); close() }}>
                Zaman aralığını uygula
              </Button>
            </Stack>
          </Box>
          <Divider orientation="vertical" flexItem />
          {/* Hızlı aralıklar */}
          <Box sx={{ width: 220, py: 1 }}>
            <Typography variant="overline" color="text.secondary" sx={{ px: 2 }}>Hızlı aralıklar</Typography>
            <MenuList dense disablePadding>
              <Option value="all" text="Son 1000 kayıt" />
              <Divider sx={{ my: 0.5 }} />
              {QUICK_RANGES.map((q) => <Option key={q.value} value={q.value} text={q.label} />)}
            </MenuList>
          </Box>
        </Box>
      </Popover>
    </>
  )
}
