import ReplayIcon from '@mui/icons-material/Replay'
import { Alert, Button } from '@mui/material'
import { apiErrorMessage } from '../api/client'

/** Sayfa/liste sorgusu (useQuery) başarısız olduğunda skeleton yerine gösterilir.
 *  Bu olmadan `isLoading=false, data=undefined` durumunda sayfa SONSUZA DEK
 *  yükleniyor (skeleton/boş) görünürdü — kullanıcıya neden + yeniden dene sunar. */
export default function QueryError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <Alert
      severity="error"
      action={
        <Button color="inherit" size="small" startIcon={<ReplayIcon />} onClick={onRetry}>
          Yeniden Dene
        </Button>
      }
    >
      Veriler yüklenemedi: {apiErrorMessage(error)}
    </Alert>
  )
}
