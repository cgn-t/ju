/** Kullanıcı rolü ve ekip tipi etiketleri — Kullanıcılar, Ekipler ve Ekip Üyelikleri ortak kullanır. */
import type { AppUser } from '../api/types'
import { includesFolded } from './textMatch'

export type ChipColor = 'default' | 'error' | 'primary' | 'warning' | 'info' | 'success'

export const ROLE_CHIP: Record<string, { label: string; color: ChipColor }> = {
  admin: { label: 'Yönetici', color: 'error' },
  editor: { label: 'Ekip Editörü', color: 'info' },
  viewer: { label: 'Ekip İzleyici', color: 'success' },
  allviewer: { label: 'Genel İzleyici', color: 'default' },
  none: { label: 'Yetkisiz', color: 'warning' },
}

// Rol atama seçenekleri — açıklamalar seçim listesinde gösterilir.
export const ROLE_OPTIONS: { value: string; label: string; hint: string }[] = [
  { value: 'admin', label: 'Yönetici', hint: 'Her şeyi görür ve düzenler' },
  { value: 'editor', label: 'Ekip Editörü', hint: 'Yalnız kendi SY ekiplerini görür ve düzenler' },
  { value: 'viewer', label: 'Ekip İzleyici', hint: 'Yalnız kendi SY ekiplerini görür (düzenleyemez)' },
  { value: 'allviewer', label: 'Genel İzleyici', hint: 'Her şeyi görür ama düzenleyemez' },
  { value: 'none', label: 'Yetkisiz', hint: 'Rol atanmadı — hiçbir şey göremez' },
]

export const TEAM_TYPE_LABEL: Record<string, string> = {
  ADMIN: 'Yönetici (tam yetki)', VIEWER: 'İzleyici (salt-okur)', SY: 'SY ekibi', UG: 'UG',
}
export const TEAM_TYPE_COLOR: Record<string, 'error' | 'warning' | 'primary' | 'default'> = {
  ADMIN: 'error', VIEWER: 'warning', SY: 'primary', UG: 'default',
}

/** Ekip Editörü/İzleyici rolü SY ekibi olmadan hiçbir şey göremez — kapsam eksik. */
export function missingScope(u: Pick<AppUser, 'role' | 'sy_team_ids'>): boolean {
  return (u.role === 'editor' || u.role === 'viewer') && !(u.sy_team_ids?.length)
}

/** Avatar baş harfleri: "Ahmet Yıldız" → "AY", yoksa kullanıcı adının ilk iki harfi. */
export function initials(fullName: string | null | undefined, username: string): string {
  const parts = (fullName ?? '').trim().split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toLocaleUpperCase('tr-TR')
  if (parts.length === 1) return parts[0].slice(0, 2).toLocaleUpperCase('tr-TR')
  return username.slice(0, 2).toLocaleUpperCase('tr-TR')
}

/** Türkçe duyarlı "içerir" araması (İ/ı ve ASCII yazım doğru eşleşir: "ISMAIL" → "İsmail"). */
export function includesTr(haystack: (string | null | undefined)[], needle: string): boolean {
  const n = needle.trim()
  if (!n) return true
  return haystack.some((h) => includesFolded(h, n))
}

/** Son giriş aralığı (filtre değeri). */
export type LoginBucket = 'd1' | 'd7' | 'd30' | 'old30' | 'old90' | 'never'
export const LOGIN_BUCKETS: { value: LoginBucket; label: string }[] = [
  { value: 'd1', label: 'Son 24 saat' },
  { value: 'd7', label: 'Son 7 gün' },
  { value: 'd30', label: 'Son 30 gün' },
  { value: 'old30', label: '30 günden eski' },
  { value: 'old90', label: '90 günden eski' },
  { value: 'never', label: 'Hiç giriş yapmadı' },
]
export function inLoginBucket(lastLogin: string | null | undefined, b: LoginBucket): boolean {
  if (b === 'never') return !lastLogin
  if (!lastLogin) return false
  const days = (Date.now() - new Date(lastLogin).getTime()) / 86_400_000
  switch (b) {
    case 'd1': return days <= 1
    case 'd7': return days <= 7
    case 'd30': return days <= 30
    case 'old30': return days > 30
    case 'old90': return days > 90
  }
}
