import { useCallback, useMemo, useSyncExternalStore } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

/**
 * Görünüm durumunu URL sorgu parametrelerinde tutan küçük katman — sayfa yenilenince ya da
 * bağlantı paylaşılınca aynı ekran (sekme, filtre, açık panel) açılır.
 *
 * NEDEN react-router'ın useSearchParams'ı değil: onun setSearchParams'ı adresi SON RENDER'daki
 * (bayat) halinden hesaplar ve güncellemeyi startTransition ile geciktirir. Kontrollü bir arama
 * kutusunda hızlı yazınca karakterler kaybolur ("jumbo" → "o"), aynı anda yazılan iki parametre
 * birbirini ezer. Burada OKUMA window.location'dan anında (useSyncExternalStore), YAZMA her zaman
 * GÜNCEL adresin üzerine yapılır.
 */

const URL_EVENT = 'jumbo:urlchange'

function subscribe(cb: () => void) {
  window.addEventListener('popstate', cb)
  window.addEventListener(URL_EVENT, cb)
  return () => {
    window.removeEventListener('popstate', cb)
    window.removeEventListener(URL_EVENT, cb)
  }
}
const getSearch = () => window.location.search

/** Güncel sorgu parametreleri (anlık). */
export function useUrlParams(): URLSearchParams {
  useLocation()  // router içi gezinmelerde (Link/navigate) de yeniden oku
  const search = useSyncExternalStore(subscribe, getSearch)
  return useMemo(() => new URLSearchParams(search), [search])
}

/** Parametreleri GÜNCEL adres üzerinde değiştirir. Geçmişe kayıt eklemez (replace): Geri tuşu
 *  sekme sekme dolaşmaz, önceki sayfaya döner. */
export function useUrlWriter() {
  const navigate = useNavigate()
  return useCallback((mutate: (p: URLSearchParams) => void) => {
    const p = new URLSearchParams(window.location.search)
    mutate(p)
    const qs = p.toString()
    if (qs === window.location.search.replace(/^\?/, '')) return
    const search = qs ? `?${qs}` : ''
    // Adresi hemen güncelle (sonraki yazımlar ve okumalar bunu görsün), router'ı da senkronla
    window.history.replaceState(window.history.state, '', `${window.location.pathname}${search}${window.location.hash}`)
    navigate({ pathname: window.location.pathname, search, hash: window.location.hash },
             { replace: true, preventScrollReset: true })
    window.dispatchEvent(new Event(URL_EVENT))
  }, [navigate])
}

/**
 * useState gibi çalışır ama değeri URL'de tutar (?key=değer). Varsayılan değerde parametre
 * kaldırılır (adres temiz kalır). `allowed` verilirse dışındaki değer yok sayılır.
 */
export function useUrlState<T extends string>(
  key: string, defaultValue: T, allowed?: readonly T[],
): [T, (value: T) => void] {
  const params = useUrlParams()
  const write = useUrlWriter()
  const raw = params.get(key)
  const value = (raw !== null && (!allowed || allowed.includes(raw as T)) ? raw : defaultValue) as T

  const setValue = useCallback((next: T) => {
    write((p) => {
      if (next === defaultValue) p.delete(key)
      else p.set(key, next)
    })
  }, [key, defaultValue, write])

  return [value, setValue]
}

/** Birden çok parametreyi tek seferde değiştirir. Boş string / null değer parametreyi siler. */
export function useUrlPatch() {
  const write = useUrlWriter()
  return useCallback((patch: Record<string, string | null>) => {
    write((p) => {
      for (const [k, v] of Object.entries(patch)) {
        if (v === null || v === '') p.delete(k)
        else p.set(k, v)
      }
    })
  }, [write])
}

/** Kimlik (sayı) tutan URL durumu — açık detay paneli gibi (?cert=42). null = parametre yok. */
export function useUrlId(key: string): [number | null, (id: number | null) => void] {
  const [raw, setRaw] = useUrlState<string>(key, '')
  const n = /^\d+$/.test(raw) ? Number(raw) : null
  const set = useCallback((id: number | null) => setRaw(id === null ? '' : String(id)), [setRaw])
  return [n, set]
}
