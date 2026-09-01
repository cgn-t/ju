import writeXlsxFile from 'write-excel-file/browser'
import type { SheetData } from 'write-excel-file/browser'

/** Satırları gerçek .xlsx dosyası olarak indirir. Önceki CSV metin-tabanlı yaklaşım, çok
 * satırlı hücrelerde (ör. Domain notu) Windows Excel'in tırnaklanmış alan içindeki satır
 * sonunu gerçek satır sonu sanıp hücreyi bölmesine yol açıyordu — .xlsx yapılandırılmış bir
 * format olduğundan hücre içeriği parser tahminine bağlı kalmadan doğru saklanır. */
export function exportSheet(
  filename: string,
  headers: string[],
  rows: (string | number | null | undefined)[][],
) {
  const toCell = (v: string | number | null | undefined) => ({
    value: v === null || v === undefined ? '' : String(v),
    type: String,
    wrap: true,
  })
  const data: SheetData = [
    headers.map((h) => ({ value: h, type: String, fontWeight: 'bold' as const })),
    ...rows.map((r) => r.map(toCell)),
  ]
  writeXlsxFile(data).toFile(filename).catch((err: unknown) => {
    console.error('xlsx dışa aktarımı başarısız', err)
  })
}
