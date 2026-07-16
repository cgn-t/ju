import { Autocomplete, Box, Chip, TextField, Typography, createFilterOptions } from '@mui/material'
import type { Certificate } from '../api/types'
import { daysLeftColor, daysLeftLabel, MONO_FONT, nodeColors } from '../theme'

interface Props {
  options: Certificate[]
  value: Certificate | null
  onChange: (cert: Certificate | null) => void
  label: string
  disabledIds?: Set<number>
  disabledLabel?: string // pasif seçeneklerin yanında görünen rozet (ör. "zaten bağlı")
  sx?: object
}

// SKI sertifikanın kimliğidir — ad, SKI, seri no ve SAN üzerinden arama yapılabilir
const filter = createFilterOptions<Certificate>({
  stringify: (c) =>
    `${c.name} ${c.subject_key_identifier ?? ''} ${c.serial_number ?? ''} ${c.san ?? ''}`,
})

/** Sertifika bağlama noktalarında kullanılan ortak seçici: her seçenekte tür, kalan gün
 *  ve SubjectKeyIdentifier görünür; yanlış sertifikaya bağlanma riskini azaltır. */
export default function CertificatePicker({
  options, value, onChange, label, disabledIds, disabledLabel = 'zaten bağlı', sx,
}: Props) {
  return (
    <Autocomplete
      size="small" sx={sx} options={options} value={value}
      onChange={(_, v) => onChange(v)}
      filterOptions={filter}
      getOptionLabel={(c) => c.name}
      isOptionEqualToValue={(a, b) => a.id === b.id}
      getOptionDisabled={(c) => disabledIds?.has(c.id) ?? false}
      renderOption={({ key, ...props }, c) => (
        <Box component="li" key={key} {...props}
             sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start !important', gap: 0.25 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
            <Chip size="small" label={c.cert_type[0].toUpperCase()}
                  sx={{ bgcolor: nodeColors[c.cert_type], color: 'rgba(0,0,0,0.87)',
                        fontWeight: 700, width: 26, flexShrink: 0 }} />
            <Typography variant="body2" noWrap sx={{ flexGrow: 1, fontWeight: 500 }}>{c.name}</Typography>
            {disabledIds?.has(c.id) && <Chip size="small" variant="outlined" label={disabledLabel} />}
            <Chip size="small" color={daysLeftColor(c.days_left)} label={daysLeftLabel(c.days_left)} />
          </Box>
          <Typography variant="caption" color="text.secondary" noWrap
                      sx={{ fontFamily: MONO_FONT, fontSize: 10.5, pl: '34px', width: '100%' }}>
            {c.subject_key_identifier ?? '—'}
          </Typography>
        </Box>
      )}
      renderInput={(params) => (
        // NOT: slotProps/FormHelperTextProps kullanma — Autocomplete params'ının
        // input kablolamasını ezer (MUI v7); helper stili sx ile hedeflenir
        <TextField
          {...params} label={label}
          helperText={value?.subject_key_identifier ?? undefined}
          sx={{ '& .MuiFormHelperText-root': { fontFamily: MONO_FONT, fontSize: 10.5, mx: 0.5 } }}
        />
      )}
    />
  )
}
