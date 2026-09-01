import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { AppUser } from '../api/types'

/** Uyum/Devir Önerisi/Keşif/Dağıtım sayfa görünürlüğü. ['auth-me'] cache key'i
 * DomainFormDialog/CertMap/Applications ile PAYLAŞILIR — ek ağ isteği çıkarmaz.
 *
 * `nav`: üst navigasyon linki görünürlüğü. Kök seviyedeki alanlardan FARKI: SY ekip üyeliği
 * carve-out'u yok (Devir Önerisi/Sertifika Talepleri'nde SY üyesi, Ayarlar>Erişim kapalıyken
 * bile ROTAYA erişebilir — DomainDetailDrawer'daki 'Onaya git' linki ve onay iş akışı bozulmaz;
 * yalnız üst menüde link, switch açık olmadıkça gizlenir). Route guard (PageAccessRoute) kök
 * seviyeyi kullanmaya devam eder. */
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
    issuance: data?.page_access?.issuance ?? false,
    nav: {
      policy: data?.nav_page_access?.policy ?? false,
      proposals: data?.nav_page_access?.proposals ?? false,
      discovery: data?.nav_page_access?.discovery ?? false,
      deployments: data?.nav_page_access?.deployments ?? false,
      issuance: data?.nav_page_access?.issuance ?? false,
    },
  }
}
