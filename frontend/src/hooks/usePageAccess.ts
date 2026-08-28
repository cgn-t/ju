import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { AppUser } from '../api/types'

/** Uyum/Devir Önerisi/Keşif/Dağıtım sayfa görünürlüğü. ['auth-me'] cache key'i
 * DomainFormDialog/CertMap/Applications ile PAYLAŞILIR — ek ağ isteği çıkarmaz. */
export function usePageAccess() {
  const { data, isLoading } = useQuery<AppUser>({
    queryKey: ['auth-me'],
    queryFn: async () => (await api.get('/auth/me')).data,
  })
  return {
    isLoading,
    policy: data?.page_access?.policy ?? false,
    proposals: data?.page_access?.proposals ?? false,
    discovery: data?.page_access?.discovery ?? false,
    deployments: data?.page_access?.deployments ?? false,
  }
}
