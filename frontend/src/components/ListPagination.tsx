import { TablePagination } from '@mui/material'
import { PAGE_SIZES } from '../hooks/usePaging'

/** Sayfalı listelerin ortak alt çubuğu (Türkçe etiketler, sayfa başına satır seçimi). */
export default function ListPagination({ total, page, size, onPage, onSize, unit = 'kayıt' }: {
  total: number
  page: number
  size: number
  onPage: (p: number) => void
  onSize: (n: number) => void
  unit?: string
}) {
  return (
    <TablePagination
      component="div"
      count={total}
      page={total === 0 ? 0 : Math.min(page, Math.max(0, Math.ceil(total / size) - 1))}
      onPageChange={(_e, p) => onPage(p)}
      rowsPerPage={size}
      onRowsPerPageChange={(e) => onSize(parseInt(e.target.value, 10))}
      rowsPerPageOptions={[...PAGE_SIZES]}
      labelRowsPerPage="Sayfa başına"
      labelDisplayedRows={({ from, to, count }) => `${from}–${to} / ${count} ${unit}`}
      showFirstButton showLastButton
      getItemAriaLabel={(type) => ({ first: 'İlk sayfa', last: 'Son sayfa', next: 'Sonraki sayfa', previous: 'Önceki sayfa' })[type]}
    />
  )
}
