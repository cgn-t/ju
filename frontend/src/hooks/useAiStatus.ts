import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export type AiStatus = { enabled: boolean; name: string; suggestions?: string[]; guide_url?: string | null }

// AI simgesi, sohbet başlığı ve hazır sorular; guide_url sol menüdeki Kullanım Kılavuzu linki
// (kurum wiki'si — AI kapalı olsa da gelir).
export function useAiStatus() {
  return useQuery<AiStatus>({
    queryKey: ['ai-status'],
    queryFn: async () => (await api.get('/ai/status')).data,
    staleTime: 5 * 60_000,
  })
}
