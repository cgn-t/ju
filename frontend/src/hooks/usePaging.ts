import { useCallback, useEffect, useRef, useState } from 'react'
import { useUrlParams, useUrlPatch } from './useUrlState'

/**
 * Sunucu-taraflı sayfalama durumu — URL'de tutulur (?p=2&n=100; 1. sayfa ve varsayılan boyut
 * adrese yazılmaz). Paylaşılan bağlantı aynı sayfayı açar. `filterKey` değişince (arama, filtre,
 * sıralama) 1. sayfaya dönülür; ilk açılışta adresteki sayfa korunur.
 */
export const PAGE_SIZES = [25, 50, 100, 200] as const

export function usePaging(filterKey: string, defaultSize = 50) {
  const params = useUrlParams()
  const patch = useUrlPatch()
  const rawPage = Number(params.get('p'))
  const page = Number.isInteger(rawPage) && rawPage > 1 ? rawPage - 1 : 0
  const rawSize = Number(params.get('n'))
  const size = (PAGE_SIZES as readonly number[]).includes(rawSize) ? rawSize : defaultSize

  const setPage = useCallback((p: number) => patch({ p: p > 0 ? String(p + 1) : null }), [patch])
  const setSize = useCallback((n: number) =>
    patch({ n: n === defaultSize ? null : String(n), p: null }), [patch, defaultSize])

  const prevKey = useRef(filterKey)
  useEffect(() => {
    if (prevKey.current !== filterKey) {
      prevKey.current = filterKey
      if (page !== 0) setPage(0)
    }
  }, [filterKey, page, setPage])

  return { page, size, setPage, setSize }
}

/** Yazarken her tuşta sunucuya gitmemek için gecikmeli değer. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}
