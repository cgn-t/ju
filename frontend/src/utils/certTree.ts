import type { Certificate } from '../api/types'

export interface TreeRow {
  cert: Certificate
  depth: number
}

/** Sertifika listesini üst sertifika ilişkisine göre ağaç sırasına dizer (derinlikle). */
export function buildTree(certs: Certificate[]): TreeRow[] {
  const byParent = new Map<number | null, Certificate[]>()
  const ids = new Set(certs.map((c) => c.id))
  for (const cert of certs) {
    const key = cert.parent_id && ids.has(cert.parent_id) ? cert.parent_id : null
    byParent.set(key, [...(byParent.get(key) ?? []), cert])
  }
  const rows: TreeRow[] = []
  const walk = (parentId: number | null, depth: number) => {
    for (const cert of byParent.get(parentId) ?? []) {
      rows.push({ cert, depth })
      walk(cert.id, depth + 1)
    }
  }
  walk(null, 0)
  // Döngüye girmiş kayıtlar (A'nın üstü B, B'nin üstü A) hiçbir dala düşmez; listeden kaybolmasınlar
  const shown = new Set(rows.map((r) => r.cert.id))
  for (const cert of certs) {
    if (!shown.has(cert.id)) rows.push({ cert, depth: 0 })
  }
  return rows
}
