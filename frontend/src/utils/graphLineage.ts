/**
 * Haritada "üzerine gelince ilişkililer öne çıksın" davranışının saf mantığı.
 *
 * Bir düğümün SOY HATTI (lineage): ondan geriye doğru (kenar yönünün tersine) erişilen tüm
 * atalar + ileriye doğru erişilen tüm torunlar. Kardeşler dahil EDİLMEZ — ör. bir Leaf'in
 * üzerine gelince Intermediate ve Root'u ile bağlı domainleri yanar, aynı Intermediate'in
 * altındaki diğer Leaf'ler sönük kalır. Kenarlar yalnızca bu yürüyüşte geçilenlerdir.
 */
export interface LineageEdge { id: string; source: string; target: string }

export interface Lineage {
  nodes: Set<string>
  edges: Set<string>
  /** Atalar (başlangıç hariç) */
  up: Set<string>
  /** Torunlar (başlangıç hariç) */
  down: Set<string>
}

function walk(start: string, adj: Map<string, LineageEdge[]>, next: (e: LineageEdge) => string,
              seen: Set<string>, edgeIds: Set<string>) {
  const stack = [start]
  while (stack.length) {
    const cur = stack.pop() as string
    for (const e of adj.get(cur) ?? []) {
      edgeIds.add(e.id)
      const nb = next(e)
      if (nb !== start && !seen.has(nb)) { seen.add(nb); stack.push(nb) }
    }
  }
}

export function lineage(edges: LineageEdge[], start: string): Lineage {
  const out = new Map<string, LineageEdge[]>()
  const inc = new Map<string, LineageEdge[]>()
  for (const e of edges) {
    if (!out.has(e.source)) out.set(e.source, [])
    if (!inc.has(e.target)) inc.set(e.target, [])
    out.get(e.source)!.push(e)
    inc.get(e.target)!.push(e)
  }
  const up = new Set<string>()
  const down = new Set<string>()
  const edgeIds = new Set<string>()
  walk(start, inc, (e) => e.source, up, edgeIds)
  walk(start, out, (e) => e.target, down, edgeIds)
  return { nodes: new Set([start, ...up, ...down]), edges: edgeIds, up, down }
}

/** Kenarın iki ucu — kenarın üzerine gelince yalnız uçlar yanar. */
export function edgeEnds(edges: LineageEdge[], edgeId: string): Lineage | null {
  const e = edges.find((x) => x.id === edgeId)
  if (!e) return null
  return { nodes: new Set([e.source, e.target]), edges: new Set([e.id]),
           up: new Set([e.source]), down: new Set([e.target]) }
}
