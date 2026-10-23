import { Autocomplete, Box, Chip, TextField, Typography, createFilterOptions } from '@mui/material'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import type { Certificate, CertificateOption } from '../api/types'
import { useDebounced } from '../hooks/usePaging'
import { daysLeftColor, daysLeftLabel, MONO_FONT, nodeColors } from '../theme'

/** Seçicinin ihtiyaç duyduğu alanlar — tam Certificate da, hafif CertificateOption da uyar. */
export type PickerCert = Pick<Certificate, 'id' | 'name' | 'cert_type'> & Partial<Pick<CertificateOption,
  'days_left' | 'subject_key_identifier' | 'serial_number' | 'san' | 'is_active'>>

interface Props<T extends PickerCert> {
  /** Yerel liste. Verilmezse `remote` ile sunucuda aranır (tüm envanter indirilmez). */
  options?: T[]
  /** Sunucu araması: /certificates/options (yazdıkça en fazla 50 sonuç). */
  remote?: { cert_type?: string; is_active?: boolean; exclude?: (c: CertificateOption) => boolean }
  value: T | null
  onChange: (cert: T | null) => void
  label: string
  disabledIds?: Set<number>
  disabledLabel?: string // pasif seçeneklerin yanında görünen rozet (ör. "zaten bağlı")
  sx?: object
}

// SKI sertifikanın kimliğidir — ad, SKI, seri no ve SAN üzerinden arama yapılabilir
const localFilter = createFilterOptions<PickerCert>({
  stringify: (c) =>
    `${c.name} ${c.subject_key_identifier ?? ''} ${c.serial_number ?? ''} ${c.san ?? ''}`,
})

/** Sertifika bağlama noktalarında kullanılan ortak seçici: her seçenekte tür, kalan gün
 *  ve SubjectKeyIdentifier görünür; yanlış sertifikaya bağlanma riskini azaltır. */
export default function CertificatePicker<T extends PickerCert>({
  options, remote, value, onChange, label, disabledIds, disabledLabel = 'zaten bağlı', sx,
}: Props<T>) {
  const [input, setInput] = useState(value?.name ?? '')
  const [open, setOpen] = useState(false)
  // Kutuda seçili kaydın adı duruyorsa arama boş yapılır (açınca tüm ilk sonuçlar gelsin)
  const q = useDebounced(input === value?.name ? '' : input, 250)
  const { data: found, isFetching } = useQuery<CertificateOption[]>({
    queryKey: ['certificate-options', remote?.cert_type, remote?.is_active, q],
    queryFn: async () => (await api.get('/certificates/options', {
      params: { q: q || undefined, cert_type: remote?.cert_type, is_active: remote?.is_active, limit: 50 },
    })).data,
    enabled: !!remote && open,
    placeholderData: keepPreviousData,
  })
  const remoteOptions = (found ?? []).filter((c) => !remote?.exclude?.(c)) as unknown as T[]
  const list = remote ? remoteOptions : (options ?? [])

  return (
    <Autocomplete
      size="small" sx={sx} options={list} value={value}
      open={open} onOpen={() => setOpen(true)} onClose={() => setOpen(false)}
      onChange={(_, v) => onChange(v)}
      inputValue={remote ? input : undefined}
      onInputChange={remote ? (_, v) => setInput(v) : undefined}
      filterOptions={remote ? (x) => x : (o, st) => localFilter(o, st as never) as T[]}
      loading={!!remote && isFetching}
      loadingText="Aranıyor…"
      noOptionsText={remote ? (input ? 'Eşleşen sertifika yok' : 'Aramak için ad, SKI veya Serial Number yazın') : 'Seçenek yok'}
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
