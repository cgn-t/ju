import { useEffect } from 'react'

/** Tarayıcı sekmesi başlığını "JUMBO · <sayfa>" yapar. */
export function useDocumentTitle(page: string) {
  useEffect(() => {
    const previous = document.title
    document.title = `JUMBO · ${page}`
    return () => { document.title = previous }
  }, [page])
}
