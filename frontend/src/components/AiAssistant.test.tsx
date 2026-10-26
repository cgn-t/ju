import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { renderPage } from '../test/render'
import AiAssistant from './AiAssistant'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
const apiGet = vi.mocked(api.get)
const apiPost = vi.mocked(api.post)

describe('AiAssistant', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    sessionStorage.clear()
  })

  it('AI kapalıyken simge görünmez', async () => {
    apiGet.mockResolvedValue({ data: { enabled: false, name: 'Jumbo AI' } })
    renderPage(<AiAssistant />)
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/ai/status'))
    expect(screen.queryByRole('button', { name: /sor$/ })).toBeNull()
  })

  it('soruyu gönderir, cevaptaki kayıt bağlantısını gösterir', async () => {
    apiGet.mockResolvedValue({ data: { enabled: true, name: 'Fil' } })
    apiPost.mockResolvedValue({ data: {
      answer: '1 sertifika var:\n- [web.firma.local](/certificates?cert=7) — **12 gün** kaldı',
      tools_used: ['sertifika_ara'], tool_mode: true } })
    renderPage(<AiAssistant />, { url: '/domains' })
    await userEvent.click(await screen.findByRole('button', { name: "Fil'a sor" }))
    await userEvent.type(screen.getByPlaceholderText('Sorunuzu yazın…'), 'Bitecekler?{Enter}')
    const link = await screen.findByRole('link', { name: 'web.firma.local' })
    expect(link.getAttribute('href')).toBe('/certificates?cert=7')
    expect(screen.getByText('12 gün').tagName).toBe('B')
    expect(apiPost).toHaveBeenCalledWith('/ai/chat', {
      messages: [{ role: 'user', content: 'Bitecekler?' }], page: '/domains' })
  })

  it('servis hatasını sohbet içinde gösterir', async () => {
    apiGet.mockResolvedValue({ data: { enabled: true, name: 'Fil' } })
    apiPost.mockRejectedValue({ isAxiosError: true, response: { data: { detail: 'AI servisi anahtarı kabul etmedi' } } })
    renderPage(<AiAssistant />)
    await userEvent.click(await screen.findByRole('button', { name: "Fil'a sor" }))
    await userEvent.click(screen.getByText('Onay bekleyen değişiklik talepleri neler?'))
    expect(await screen.findByText(/anahtarı kabul etmedi/)).toBeTruthy()
  })
})
