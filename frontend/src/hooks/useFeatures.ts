import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { AppUser } from '../api/types'

// Ortam/şema durumuna bağlı özellikler (GET /auth/me → features):
//   db_console    — Veritabanı Değişiklikleri sayfası (admin + ortamda DB_CONSOLE=1)
//   standard_name — StandartAd kolonu veritabanında var (v3.9.39 betiği çalıştırıldı)
export function useFeatures(): { db_console: boolean; standard_name: boolean } {
  const { data } = useQuery<AppUser>({ queryKey: ['auth-me'], queryFn: async () => (await api.get('/auth/me')).data })
  return { db_console: !!data?.features?.db_console, standard_name: !!data?.features?.standard_name }
}
