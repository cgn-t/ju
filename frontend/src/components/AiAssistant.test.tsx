import { fireEvent, screen, waitFor } from '@testing-library/react'
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
    localStorage.removeItem('jumbo.ai.launcherPos')
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
      tools_used: ['sertifika_ara', 'kilavuz_ara', 'veri_sorgula', 'veri_tablolari'], tool_mode: true } })
    renderPage(<AiAssistant />, { url: '/domains' })
    await userEvent.click(await screen.findByRole('button', { name: "Fil'a sor" }))
    await userEvent.type(screen.getByPlaceholderText('Sorunuzu yazın…'), 'Bitecekler?{Enter}')
    const link = await screen.findByRole('link', { name: 'web.firma.local' })
    expect(link.getAttribute('href')).toBe('/certificates?cert=7')
    expect(screen.getByText('12 gün').tagName).toBe('B')
    expect(screen.getByText('Baktığı yerler: SSL Sertifikaları, Kullanım Kılavuzu, Jumbo veritabanı')).toBeTruthy()
    expect(screen.queryByText(/Bu sayfa/)).toBeNull()   // v3.9.16: panelde sayfa adı yazmaz (AI'a yine gider)
    expect(apiPost).toHaveBeenCalledWith('/ai/chat', {
      messages: [{ role: 'user', content: 'Bitecekler?' }], page: '/domains' })
  })

  it('kılavuz cevabındaki wiki linki yeni sekmede açılır', async () => {
    apiGet.mockResolvedValue({ data: ON })
    apiPost.mockResolvedValue({ data: {
      answer: '1. **Domainler** > **Yeni Domain**\nAyrıntı: [Domain ekleme](https://wiki.firma.local/display/JUMBO/Domain+ekleme)',
      tools_used: ['kilavuz_ara'], tool_mode: true } })
    renderPage(<AiAssistant />)
    await userEvent.click(await screen.findByRole('button', { name: "Fil'a sor" }))
    await userEvent.type(screen.getByPlaceholderText('Sorunuzu yazın…'), 'Domain nasıl eklenir?{Enter}')
    const link = await screen.findByRole('link', { name: 'Domain ekleme' })
    expect(link.getAttribute('href')).toBe('https://wiki.firma.local/display/JUMBO/Domain+ekleme')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(screen.getByText('Baktığı yerler: Kullanım Kılavuzu')).toBeTruthy()
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

  it('düğme sürüklenince panel açılmaz, bırakıldığı yer hatırlanır; sağ tıkla varsayılan yere döner', async () => {
    apiGet.mockResolvedValue({ data: ON })
    renderPage(<AiAssistant />)
    const btn = await screen.findByRole('button', { name: "Fil'a sor" })
    fireEvent.pointerDown(btn, { button: 0, clientX: 900, clientY: 700, pointerId: 1 })
    fireEvent.pointerMove(btn, { clientX: 400, clientY: 500, pointerId: 1 })
    btn.getBoundingClientRect = () => ({ left: 420, right: 488, top: 400, bottom: 468, width: 68, height: 68, x: 20, y: 400, toJSON: () => ({}) })
    fireEvent.pointerUp(btn, { clientX: 54, clientY: 434, pointerId: 1 })
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(JSON.parse(localStorage.getItem('jumbo.ai.launcherPos')!).right).toBe((document.documentElement.clientWidth || window.innerWidth) - 488)
    fireEvent.contextMenu(btn)
    await userEvent.click(await screen.findByText('Varsayılan yere taşı (sağ alt)'))
    expect(localStorage.getItem('jumbo.ai.launcherPos')).toBeNull()
  })
})
