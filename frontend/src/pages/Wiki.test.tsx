import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { api } from '../api/client'
import { renderPage } from '../test/render'
import Wiki, { type WikiPage } from './Wiki'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
const apiGet = vi.mocked(api.get)
const apiPut = vi.mocked(api.put)

const page = (id: number, slug: string, title: string, category: string, body: string): WikiPage =>
  ({ id, slug, title, category, body, sort_order: id * 10, updated_by: null, updated_at: null })
const PAGES = [
  page(1, 'jumbo-nedir', 'Jumbo nedir?', 'Başlarken', '## Jumbo ne yapar?\n- Sertifikaları tutar.\n> Not: AI simgesi'),
  page(2, 'domain-ekleme', 'Domain ekleme', 'Domainler',
       '1. [Domainler](/domains) ekranında **Yeni Domain**e basın.\n2. Kaydedin.'),
  page(3, 'degisiklik-talepleri', 'Değişiklik talepleri', 'Onay ve Bildirimler', 'İŞLEM onayı'),
]

const routes = (
  <Routes>
    <Route path="/wiki" element={<Wiki />} />
    <Route path="/wiki/:slug" element={<Wiki />} />
  </Routes>
)

describe('Kullanım Kılavuzu', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPut.mockReset()
    apiGet.mockResolvedValue({ data: PAGES })
  })

  it('/wiki ilk sayfayı açar; başlık, madde ve not kutusu görünür', async () => {
    renderPage(routes, { url: '/wiki', role: 'viewer' })
    expect(await screen.findByRole('heading', { name: 'Jumbo nedir?' })).toBeTruthy()
    await waitFor(() => expect(window.location.pathname).toBe('/wiki/jumbo-nedir'))
    expect(screen.getByRole('heading', { name: 'Jumbo ne yapar?' })).toBeTruthy()
    expect(screen.getByText('Sertifikaları tutar.').tagName).toBe('LI')
    expect(screen.getByText('Not: AI simgesi')).toBeTruthy()
    // İzleyici düzenleyemez
    expect(screen.queryByRole('button', { name: 'Düzenle' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Yeni Sayfa' })).toBeNull()
  })

  it('numaralı adımlar ve iç bağlantılar; Türkçe harf duyarsız arama', async () => {
    renderPage(routes, { url: '/wiki/domain-ekleme' })
    expect(await screen.findByRole('heading', { name: 'Domain ekleme' })).toBeTruthy()
    const article = screen.getByRole('article')
    expect(within(article).getByRole('link', { name: 'Domainler' }).getAttribute('href')).toBe('/domains')
    expect(article.querySelector('ol')?.children.length).toBe(2)
    await userEvent.type(screen.getByPlaceholderText('Kılavuzda ara'), 'islem')
    const nav = screen.getByRole('list', { name: 'Kılavuz sayfaları' })
    expect(within(nav).getByText('Değişiklik talepleri')).toBeTruthy()
    expect(within(nav).queryByText('Domain ekleme')).toBeNull()
  })

  it('yönetici sayfayı düzenler; önizleme yazarken güncellenir', async () => {
    apiPut.mockResolvedValue({ data: { ...PAGES[1], body: 'yeni' } })
    renderPage(routes, { url: '/wiki/domain-ekleme' })
    await userEvent.click(await screen.findByRole('button', { name: 'Düzenle' }))
    const content = screen.getByLabelText('İçerik')
    await userEvent.clear(content)
    await userEvent.type(content, '## Önizleme başlığı')
    expect(screen.getByRole('heading', { name: 'Önizleme başlığı' })).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: 'Kaydet' }))
    await waitFor(() => expect(apiPut).toHaveBeenCalledWith('/wiki/2', {
      title: 'Domain ekleme', category: 'Domainler', sort_order: 20, body: '## Önizleme başlığı' }))
  })
})
