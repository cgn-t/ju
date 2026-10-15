/** Audit Log zaman biçimlendirme ve hazır tarih aralıkları. */

/** API zamanı İstanbul ofsetli ISO döner; tarayıcı yerelinde gösterilir (tr-TR). */
export function formatAuditTime(iso: string, withSeconds = false): string {
  const d = new Date(iso)
  return d.toLocaleString('tr-TR', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}),
  })
}

export function relativeTime(iso: string): string {
  const sec = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (sec < 45) return 'az önce'
  const min = Math.round(sec / 60)
  if (min < 60) return `${min} dk önce`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr} saat önce`
  const day = Math.round(hr / 24)
  if (day < 31) return `${day} gün önce`
  const mon = Math.round(day / 30)
  if (mon < 12) return `${mon} ay önce`
  return `${Math.round(mon / 12)} yıl önce`
}

/** YYYY-MM-DD (yerel takvim günü — sunucu İstanbul günü olarak yorumlar). */
export function isoDay(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export type TimePreset = 'all' | 'today' | '7d' | '30d' | 'this_month' | 'last_month' | 'custom'

export const TIME_PRESETS: { value: TimePreset; label: string }[] = [
  { value: 'all', label: 'Tümü (son 1000 kayıt)' },
  { value: 'today', label: 'Bugün' },
  { value: '7d', label: 'Son 7 gün' },
  { value: '30d', label: 'Son 30 gün' },
  { value: 'this_month', label: 'Bu ay' },
  { value: 'last_month', label: 'Geçen ay' },
  { value: 'custom', label: 'Özel aralık…' },
]

/** Hazır aralık → [başlangıç, bitiş] (dahil). 'custom' / 'all' için null döner. */
export function presetRange(p: TimePreset, now = new Date()): [string, string] | null {
  const y = now.getFullYear(), m = now.getMonth()
  const back = (days: number) => { const d = new Date(now); d.setDate(d.getDate() - days); return d }
  switch (p) {
    case 'today': return [isoDay(now), isoDay(now)]
    case '7d': return [isoDay(back(6)), isoDay(now)]
    case '30d': return [isoDay(back(29)), isoDay(now)]
    case 'this_month': return [isoDay(new Date(y, m, 1)), isoDay(now)]
    case 'last_month': return [isoDay(new Date(y, m - 1, 1)), isoDay(new Date(y, m, 0))]
    default: return null
  }
}
