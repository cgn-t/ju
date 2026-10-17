import type { ChainImportResult } from '../api/types'

// Zincir içe aktarma sonucu — domain formu ve domain detayı AYNI mesajı gösterir.
export function chainImportSummary(r: ChainImportResult): string {
  const parts: string[] = []
  if (r.created.length) parts.push(`${r.created.length} sertifika eklendi`)
  if (r.existing.length) parts.push(`${r.existing.length} zaten kayıtlıydı`)
  if (r.mapped_server) parts.push(`"${r.mapped_server}" server olarak bağlandı`)
  if (r.superseded.length) parts.push(`${r.superseded.length} devir önerisi oluşturuldu (SY onayı bekliyor)`)
  return parts.join(', ') || 'değişiklik yok'
}

// Sunucuda duran ama envanterde pasif olan sertifikalar bağlanmaz — kullanıcı bilmeli.
export function chainImportInactiveWarning(r: ChainImportResult): string | null {
  const names = r.inactive ?? []
  if (!names.length) return null
  return `Sunucuda pasif sertifika sunuluyor, domaine bağlanmadı: ${names.join(', ')}. `
    + 'Sunucudaki sertifikanın yenilenmesi gerekiyor olabilir.'
}
