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

export type TimePreset = 'all' | '12h' | '24h' | '2d' | '7d' | '30d' | 'custom'

/** Grafana tarzı hızlı aralıklar (kayan pencere; saat → sunucuya since_hours). */
export const QUICK_RANGES: { value: Exclude<TimePreset, 'all' | 'custom'>; label: string; hours: number }[] = [
  { value: '12h', label: 'Son 12 saat', hours: 12 },
  { value: '24h', label: 'Son 24 saat', hours: 24 },
  { value: '2d', label: 'Son 2 gün', hours: 48 },
  { value: '7d', label: 'Son 7 gün', hours: 168 },
  { value: '30d', label: 'Son 30 gün', hours: 720 },
]

export const TIME_PRESETS: { value: TimePreset; label: string }[] = [
  { value: 'all', label: 'Son 1000 kayıt' },
  ...QUICK_RANGES.map(({ value, label }) => ({ value, label })),
  { value: 'custom', label: 'Özel aralık' },
]

export function presetHours(p: TimePreset): number | undefined {
  return QUICK_RANGES.find((q) => q.value === p)?.hours
}

/** datetime-local değeri (YYYY-MM-DDTHH:mm, yerel saat). */
export function toLocalInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${isoDay(d)}T${p(d.getHours())}:${p(d.getMinutes())}`
}

/** "2026-10-15T08:00" → "15.10.2026 08:00" */
export function formatLocalInput(v: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(v)
  return m ? `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}` : v
}
