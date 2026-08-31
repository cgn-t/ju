/** Saniyeyi "1dk 24sn" / "45sn" / "2sa 03dk" biçimine çevirir — Dağıtım çalıştırma
 * geçmişinde adım/run süresi göstermek için (statik; canlı sayaç DEĞİL). */
export function formatDuration(totalSeconds: number | null | undefined): string {
  if (totalSeconds === null || totalSeconds === undefined) return '—'
  const h = Math.floor(totalSeconds / 3600)
  const m = Math.floor((totalSeconds % 3600) / 60)
  const s = Math.floor(totalSeconds % 60)
  if (h > 0) return `${h}sa ${String(m).padStart(2, '0')}dk`
  if (m > 0) return `${m}dk ${String(s).padStart(2, '0')}sn`
  return `${s}sn`
}
