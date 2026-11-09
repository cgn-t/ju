import {
  Alert, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel,
  Skeleton, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { useEffect, useMemo, useState } from 'react'
import { api, apiErrorMessage } from '../api/client'
import { MONO_FONT } from '../theme'
import { foldText } from '../utils/textMatch'
import { SearchBox } from './ListKit'

// "İsimlendirme Kuralını Uygula — Toplu" (v3.9.39, yalnız admin): her sertifika için kurala göre
// önerilen Standart Ad listelenir; admin seçer, isterse satırda düzeltir ve uygular.
type Row = { id: number; name: string; standard_name: string | null; suggested: string; same: boolean;
             collision: boolean; unknown_ca: boolean; cert_type: string; issuer: string | null;
             valid_to: string | null; environment: string | null; is_active: boolean }

const fmtDay = (d?: string | null) => (d ? new Date(d).toLocaleDateString('tr-TR') : '—')

export default function StandardNameBulkDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { enqueueSnackbar } = useSnackbar()
  const qc = useQueryClient()
  const [onlyMissing, setOnlyMissing] = useState(true)
  const [search, setSearch] = useState('')
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [edited, setEdited] = useState<Record<number, string>>({})

  const q = useQuery<{ rows: Row[] }>({
    queryKey: ['standard-name-bulk', onlyMissing],
    queryFn: async () => (await api.get('/certificates/standard-name/bulk', { params: { only_missing: onlyMissing } })).data,
    enabled: open,
  })
  const rows = useMemo(() => (q.data?.rows ?? []).filter((r) => !r.same), [q.data])
  // Varsayılan seçim: Standart Adı boş olan sertifikalar
  useEffect(() => {
    setPicked(new Set(rows.filter((r) => !r.standard_name).map((r) => r.id)))
    setEdited({})
  }, [rows])
  const visible = rows.filter((r) => !search || [r.name, r.standard_name, r.suggested, r.issuer]
    .some((v) => foldText(v ?? '').includes(foldText(search))))
  const value = (r: Row) => edited[r.id] ?? r.suggested

  const apply = useMutation({
    mutationFn: async () => (await api.post<{ changed: number }>('/certificates/standard-name/bulk', {
      items: rows.filter((r) => picked.has(r.id)).map((r) => ({ id: r.id, standard_name: value(r).trim() })),
    })).data,
    onSuccess: (r) => {
      enqueueSnackbar(`${r.changed} sertifikanın Standart Adı güncellendi`, { variant: 'success' })
      qc.invalidateQueries({ queryKey: ['certificates'] })
      qc.invalidateQueries({ queryKey: ['certificate'] })
      qc.invalidateQueries({ queryKey: ['standard-name-bulk'] })
      onClose()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })

  const toggle = (id: number) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const allOn = visible.length > 0 && visible.every((r) => picked.has(r.id))

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle>İsimlendirme Kuralını Uygula — Toplu</DialogTitle>
      <DialogContent>
        <Alert severity="info" sx={{ mb: 2 }}>
          Kural: <b style={{ fontFamily: MONO_FONT }}>CA_Tür_alanadı_BitişTarihi_ortam</b> (ör. Dgcrt_wildcard_aaaa.com_20260814_prod).
          Önerilen adı satırda değiştirebilirsiniz. Bugünkü ad (CN) değişmez; Standart Ad ayrı tutulur.
          CA kısaltmaları Ayarlar &gt; İsimlendirme'den düzenlenir.
        </Alert>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap', mb: 1 }}>
          <SearchBox value={search} onChange={setSearch} placeholder="Ad, öneri ya da Issuer ara" width={320} />
          <FormControlLabel control={<Checkbox checked={onlyMissing} onChange={(e) => setOnlyMissing(e.target.checked)} />}
                            label="Yalnız Standart Adı boş olanlar" />
          <Box sx={{ flexGrow: 1 }} />
          <Typography variant="body2" color="text.secondary">{picked.size} seçili · {rows.length} öneri</Typography>
        </Box>
        {q.isLoading ? <Skeleton variant="rounded" height={360} /> : rows.length === 0 ? (
          <Alert severity="success">Tüm sertifikaların adı kurala uygun.</Alert>
        ) : (
          <TableContainer sx={{ maxHeight: 520 }}>
            <Table size="small" stickyHeader>
              <TableHead><TableRow>
                <TableCell padding="checkbox">
                  <Checkbox checked={allOn} indeterminate={!allOn && visible.some((r) => picked.has(r.id))}
                            onChange={() => setPicked((s) => {
                              const n = new Set(s); visible.forEach((r) => (allOn ? n.delete(r.id) : n.add(r.id))); return n
                            })} />
                </TableCell>
                <TableCell sx={{ minWidth: 380, width: '45%' }}>Yeni Standart Ad</TableCell>
                <TableCell>Bugünkü ad</TableCell>
                <TableCell>Issuer</TableCell>
                <TableCell>ValidTo</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {visible.map((r) => (
                  <TableRow key={r.id} hover selected={picked.has(r.id)}>
                    <TableCell padding="checkbox"><Checkbox checked={picked.has(r.id)} onChange={() => toggle(r.id)} /></TableCell>
                    <TableCell>
                      <TextField size="small" fullWidth multiline maxRows={3} value={value(r)}
                                 onChange={(e) => { setEdited((s) => ({ ...s, [r.id]: e.target.value })); setPicked((s) => new Set(s).add(r.id)) }}
                                 slotProps={{ input: { sx: { fontFamily: MONO_FONT, fontSize: 13, fontWeight: 600, wordBreak: 'break-all' } } }} />
                      <Box sx={{ display: 'flex', gap: 0.5, mt: 0.5, flexWrap: 'wrap' }}>
                        {r.standard_name && <Chip size="small" variant="outlined" label={`Şimdiki: ${r.standard_name}`} />}
                        {r.collision && <Chip size="small" color="warning" label="Aynı ad vardı, sonuna numara eklendi" />}
                        {r.unknown_ca && <Chip size="small" color="warning" label="CA listede yok" />}
                        {!r.is_active && <Chip size="small" label="Pasif" />}
                      </Box>
                    </TableCell>
                    <TableCell sx={{ color: 'text.secondary' }}>{r.name}</TableCell>
                    <TableCell sx={{ maxWidth: 280 }}><Typography variant="body2" noWrap title={r.issuer ?? ''}>{r.issuer ?? '—'}</Typography></TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{fmtDay(r.valid_to)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Vazgeç</Button>
        <Button variant="contained" disabled={!picked.size || apply.isPending} onClick={() => apply.mutate()}>
          Seçilenleri uygula ({picked.size})
        </Button>
      </DialogActions>
    </Dialog>
  )
}
