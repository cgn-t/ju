/** Devir önerisi kaynak (via) ve öneren etiketleri — liste ve inceleme çekmecesi ortak kullanır. */
import { formatAuditTime } from './auditFormat'

export const VIA_LABEL: Record<string, string> = {
  import: 'İçe aktarma', manual: 'Elle', 'vault-sync': 'Vault senkron',
  'import-chain': 'Canlı zincir', 'live-check': 'Canlı doğrulama',
  attach: 'Elle eşleme', backfill: 'Geçiş',
}

const SYSTEM_USERS = new Set(['system', ''])

function isSystem(createdBy?: string | null): boolean {
  return SYSTEM_USERS.has(createdBy ?? '')
}

/** 3.5.0 öncesi canlı doğrulama önerileri via='attach' ile kaydediliyordu; öneren sistemse
 *  bunlar elle eşleme değil, canlı doğrulamadır. */
export function viaLabel(via?: string | null, createdBy?: string | null): string {
  if (via === 'attach' && isSystem(createdBy)) return VIA_LABEL['live-check']
  return VIA_LABEL[via ?? ''] ?? via ?? '—'
}

/** "Ahmet Yılmaz (ahmet)"; Ad Soyad yoksa yalnız kullanıcı adı, otomatikte "Sistem". */
export function proposerLabel(createdBy?: string | null, fullName?: string | null): string {
  if (isSystem(createdBy)) return 'Sistem'
  return fullName ? `${fullName} (${createdBy})` : createdBy!
}

/** "Ahmet Yılmaz (ahmet) · 16.10.2026 10:03" */
export function proposerLine(createdBy?: string | null, createdAt?: string | null,
                             fullName?: string | null): string {
  const who = proposerLabel(createdBy, fullName)
  return createdAt ? `${who} · ${formatAuditTime(createdAt)}` : who
}
