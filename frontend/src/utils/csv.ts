/** Satırları CSV'ye çevirip indirir. Excel uyumu için UTF-8 BOM ekler. */
export function exportCsv(filename: string, headers: string[], rows: (string | number | null | undefined)[][]) {
  const escape = (v: string | number | null | undefined) => {
    // Satır sonlarını normalize et: legacy MSSQL / eski uygulama kayıtları salt \r, salt \n ya
    // da \r\n tutabilir. Hepsini \r\n'e indiriyoruz — satırlar arası ayraçla (aşağıda \r\n)
    // AYNI olacak şekilde. Tırnaklanmış çok-satırlı alan içinde çıplak \n bırakmak, dosyada
    // KARIŞIK satır sonu üretiyordu (bazı yerler \n, bazı yerler \r\n) — Windows Excel bunu
    // tutarsız parse edip tırnak içindeki \n'i satır sonu sanarak hücreyi bölüyordu (macOS'ta
    // sorun çıkmıyordu çünkü Numbers/daha toleranslı parser'lar karışık satır sonuna dayanıklı).
    const s = (v === null || v === undefined ? '' : String(v)).replace(/\r\n|\r|\n/g, '\r\n')
    return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const content = [headers, ...rows].map((r) => r.map(escape).join(',')).join('\r\n')
  const blob = new Blob(['﻿' + content], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}
