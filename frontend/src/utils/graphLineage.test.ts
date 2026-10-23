import { describe, expect, it } from 'vitest'
import { edgeEnds, lineage } from './graphLineage'

// root → int → leafA → domA ; int → leafB → domB ; ayrı: root2 → leafC
const edges = [
  { id: 'h1', source: 'root', target: 'int' },
  { id: 'h2', source: 'int', target: 'leafA' },
  { id: 'h3', source: 'int', target: 'leafB' },
  { id: 'm1', source: 'leafA', target: 'domA' },
  { id: 'm2', source: 'leafB', target: 'domB' },
  { id: 'h4', source: 'root2', target: 'leafC' },
]

describe('lineage', () => {
  it('Leaf: ataları ve domainleri yanar, kardeş Leaf sönük kalır', () => {
    const l = lineage(edges, 'leafA')
    expect([...l.nodes].sort()).toEqual(['domA', 'int', 'leafA', 'root'])
    expect([...l.edges].sort()).toEqual(['h1', 'h2', 'm1'])
    expect(l.nodes.has('leafB')).toBe(false)
  })

  it('Root: tüm alt ağaç yanar, başka Root yanmaz', () => {
    const l = lineage(edges, 'root')
    expect(l.nodes.size).toBe(6)
    expect(l.nodes.has('root2')).toBe(false)
    expect(l.up.size).toBe(0)
  })

  it('Domain: kendi Leaf → Intermediate → Root zinciri yanar', () => {
    const l = lineage(edges, 'domB')
    expect([...l.up].sort()).toEqual(['int', 'leafB', 'root'])
    expect(l.down.size).toBe(0)
  })

  it('döngü olsa bile sonsuza gitmez', () => {
    const l = lineage([{ id: 'a', source: 'x', target: 'y' }, { id: 'b', source: 'y', target: 'x' }], 'x')
    expect([...l.nodes].sort()).toEqual(['x', 'y'])
  })

  it('kenarın üzerine gelince yalnız iki ucu yanar', () => {
    const l = edgeEnds(edges, 'm2')!
    expect([...l.nodes].sort()).toEqual(['domB', 'leafB'])
    expect(edgeEnds(edges, 'yok')).toBeNull()
  })
})
