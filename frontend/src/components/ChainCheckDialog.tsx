import {
  Alert, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Table,
  TableBody, TableCell, TableContainer, TableHead, TableRow, Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSnackbar } from 'notistack'
import { api, apiErrorMessage } from '../api/client'
import type { ChainCheckFinding } from '../api/types'

const KIND_LABEL: Record<ChainCheckFinding['kind'], string> = {
  type: 'Type',
  parent: 'Parent (Issuer)',
  subject_key_identifier: 'SubjectKeyIdentifier',
  authority_key_identifier: 'AuthorityKeyIdentifier',
}

/** Kayıtların türünü (kök/ara/uç) ve üst sertifikasını PEM'lerinden yeniden hesaplar; farkları
 *  gösterir, admin onaylarsa düzeltir. Eski sürümlerin yanlış yazdığı kayıtlar kendiliğinden düzelmez. */
export default function ChainCheckDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const { data, isFetching, isError, error } = useQuery<ChainCheckFinding[]>({
    queryKey: ['chain-check'],
    queryFn: async () => (await api.get<ChainCheckFinding[]>('/certificates/chain-check')).data,
    enabled: open,
    gcTime: 0,
  })
  const apply = useMutation({
    mutationFn: async () => (await api.post<ChainCheckFinding[]>('/certificates/chain-check/apply')).data,
    onSuccess: (applied) => {
      enqueueSnackbar(`${applied.length} düzeltme yapıldı`, { variant: 'success' })
      for (const key of ['certificates', 'cert-map', 'dashboard', 'chain-check']) {
        queryClient.invalidateQueries({ queryKey: [key] })
      }
      onClose()
    },
    onError: (e) => enqueueSnackbar(apiErrorMessage(e), { variant: 'error' }),
  })
  const findings = data ?? []

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Zincir Kontrolü</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Her sertifikanın türü (Root / Intermediate / Leaf) ve üst sertifikası, sertifikanın
          kendisinden yeniden hesaplanır. Kayıtta farklı olanlar aşağıda listelenir; "Düzelt" ile
          hepsi düzeltilir ve işlem kaydına yazılır. Domain ve uygulama bağlantılarına dokunulmaz.
        </Typography>
        {isFetching && <CircularProgress size={24} />}
        {isError && <Alert severity="error">{apiErrorMessage(error)}</Alert>}
        {!isFetching && !isError && findings.length === 0 && (
          <Alert severity="success">Sorun bulunamadı. Tüm kayıtların türü ve üst sertifikası doğru.</Alert>
        )}
        {!isFetching && findings.length > 0 && (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Sertifika</TableCell>
                  <TableCell>Alan</TableCell>
                  <TableCell>Şu an</TableCell>
                  <TableCell>Olması gereken</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {findings.map((f) => (
                  <TableRow key={`${f.certificate_id}-${f.kind}`}>
                    <TableCell>{f.name ?? `#${f.certificate_id}`}</TableCell>
                    <TableCell>{KIND_LABEL[f.kind]}</TableCell>
                    <TableCell>{f.current}</TableCell>
                    <TableCell><b>{f.expected}</b></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Kapat</Button>
        <Button variant="contained" disabled={findings.length === 0 || isFetching || apply.isPending}
                onClick={() => apply.mutate()}>
          Düzelt ({findings.length})
        </Button>
      </DialogActions>
    </Dialog>
  )
}
