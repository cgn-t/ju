import type { MailStatus, MailType } from '../api/types'

/** Mail geçmişi etiketleri — tür (konudan türetilir) ve durum. */

export const MAIL_TYPE: Record<MailType, { label: string; color: string }> = {
  expiry: { label: 'Süre uyarısı', color: 'warning.main' },
  expired: { label: 'Süresi geçmiş', color: 'error.main' },
  revoked: { label: 'İptal edildi', color: 'error.main' },
  deactivated: { label: 'Pasife alma', color: 'text.secondary' },
  proposal: { label: 'Devir hatırlatması', color: 'info.main' },
  other: { label: 'Diğer', color: 'text.disabled' },
}

export const MAIL_STATUS: Record<MailStatus, { label: string; color: 'success' | 'warning' | 'error' }> = {
  sent: { label: 'Gönderildi', color: 'success' },
  pending: { label: 'Kuyrukta', color: 'warning' },
  failed: { label: 'Başarısız', color: 'error' },
}
