/** Satırları CSV'ye çevirip indirir. Excel uyumu için UTF-8 BOM ekler. */
export function exportCsv(filename: string, headers: string[], rows: (string | number | null | undefined)[][]) {
  const escape = (v: string | number | null | undefined) => {
    // Satır sonlarını normalize et: legacy MSSQL / eski uygulama kayıtları salt \r ya da
    // \r\n tutabilir. Salt \r regex tetikleyicide olmadığından tırnaklanmaz; alanın içinde
    // kalan ham \r'yi Excel yeni kayıt sanıp satırı böler → prod'da CSV bozulur. Hepsini \n'e
    // indiriyoruz; \n zaten tırnaklamayı tetikler ve çok-satırlı değer tek hücrede kalır.
    const s = (v === null || v === undefined ? '' : String(v)).replace(/\r\n?/g, '\n')
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
