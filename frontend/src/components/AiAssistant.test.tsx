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
const ON = { enabled: true, name: 'Fil', suggestions: ['Onay bekleyen değişiklik talepleri neler?', 'Bitecekler?'] }

describe('AiAssistant', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    sessionStorage.clear()
    localStorage.removeItem('jumbo.ai.big')
  })

  it('AI kapalıyken simge görünmez', async () => {
    apiGet.mockResolvedValue({ data: { enabled: false, name: 'Jumbo AI' } })
    renderPage(<AiAssistant />)
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/ai/status'))
    expect(screen.queryByRole('button', { name: /sor$/ })).toBeNull()
  })

  it('soruyu gönderir, cevaptaki kayıt bağlantısını gösterir', async () => {
    apiGet.mockResolvedValue({ data: ON })
    apiPost.mockResolvedValue({ data: {
      answer: '1 sertifika var:\n- [web.firma.local](/certificates?cert=7) — **12 gün** kaldı',
      tools_used: ['sertifika_ara'], tool_mode: true } })
    renderPage(<AiAssistant />, { url: '/domains' })
    await userEvent.click(await screen.findByRole('button', { name: "Fil'a sor" }))
    await userEvent.type(screen.getByPlaceholderText('Sorunuzu yazın…'), 'Bitecekler?{Enter}')
    const link = await screen.findByRole('link', { name: 'web.firma.local' })
    expect(link.getAttribute('href')).toBe('/certificates?cert=7')
    expect(screen.getByText('12 gün').tagName).toBe('B')
    expect(screen.getByText('Baktığı yerler: SSL Sertifikaları')).toBeTruthy()
    expect(screen.getByText('Domainler')).toBeTruthy()   // "Bu sayfa: Domainler"
    expect(apiPost).toHaveBeenCalledWith('/ai/chat', {
      messages: [{ role: 'user', content: 'Bitecekler?' }], page: '/domains' })
  })

  it('servis hatasını sohbet içinde gösterir', async () => {
    apiGet.mockResolvedValue({ data: ON })
    apiPost.mockRejectedValue({ isAxiosError: true, response: { data: { detail: 'AI servisi anahtarı kabul etmedi' } } })
    renderPage(<AiAssistant />)
    await userEvent.click(await screen.findByRole('button', { name: "Fil'a sor" }))
    await userEvent.click(screen.getByText('Onay bekleyen değişiklik talepleri neler?'))
    expect(await screen.findByText(/anahtarı kabul etmedi/)).toBeTruthy()
  })

  it('hazır sorular Ayarlar\'dan gelir, sohbet sırasında menüden de sorulur; Genişlet paneli genişletir', async () => {
    apiGet.mockResolvedValue({ data: ON })
    apiPost.mockResolvedValue({ data: { answer: 'tamam', tools_used: [], tool_mode: true } })
    renderPage(<AiAssistant />)
    await userEvent.click(await screen.findByRole('button', { name: "Fil'a sor" }))
    expect(screen.getByText('Bitecekler?')).toBeTruthy()
    await userEvent.click(screen.getByText('Bitecekler?'))
    await screen.findByText('tamam')
    await userEvent.click(screen.getByRole('button', { name: 'Hazır sorular' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Onay bekleyen değişiklik talepleri neler?' }))
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(2))
    expect(apiPost.mock.calls[1][1]).toMatchObject({ messages: [
      { role: 'user', content: 'Bitecekler?' }, { role: 'assistant', content: 'tamam' },
      { role: 'user', content: 'Onay bekleyen değişiklik talepleri neler?' }] })
    await userEvent.click(screen.getByRole('button', { name: 'Genişlet' }))
    expect(screen.getByRole('button', { name: 'Daralt' })).toBeTruthy()
    expect(localStorage.getItem('jumbo.ai.big')).toBe('1')
  })

  it('hazır soru yoksa öneri ve menü düğmesi görünmez', async () => {
    apiGet.mockResolvedValue({ data: { ...ON, suggestions: [] } })
    apiPost.mockResolvedValue({ data: { answer: 'tamam', tools_used: [], tool_mode: true } })
    renderPage(<AiAssistant />)
    await userEvent.click(await screen.findByRole('button', { name: "Fil'a sor" }))
    await userEvent.type(screen.getByPlaceholderText('Sorunuzu yazın…'), 'selam{Enter}')
    await screen.findByText('tamam')
    expect(screen.queryByRole('button', { name: 'Hazır sorular' })).toBeNull()
  })
})
