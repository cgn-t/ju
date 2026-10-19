import { describe, expect, it } from 'vitest'
import type { Certificate } from '../api/types'
import { buildTree } from './certTree'

const cert = (id: number, parent_id: number | null) => ({ id, parent_id, name: `c${id}` }) as unknown as Certificate

describe('buildTree', () => {
  it('kök → ara → uç sırasını derinlikle verir', () => {
    const rows = buildTree([cert(3, 2), cert(1, null), cert(2, 1)])
    expect(rows.map((r) => [r.cert.id, r.depth])).toEqual([[1, 0], [2, 1], [3, 2]])
  })

  it('birbirinin üstü görünen kayıtlar listeden kaybolmaz', () => {
    const rows = buildTree([cert(1, null), cert(5, 6), cert(6, 5)])
    expect(rows.map((r) => r.cert.id).sort()).toEqual([1, 5, 6])
  })
})
