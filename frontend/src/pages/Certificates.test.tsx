import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import type { Certificate } from '../api/types'
import { renderPage } from '../test/render'
import { buildTree } from '../utils/certTree'
import Certificates from './Certificates'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
const apiGet = vi.mocked(api.get)

function cert(overrides: Partial<Certificate>): Certificate {
  return {
    id: 1, name: 'cert', cert_type: 'leaf', is_active: true, is_internal: false,
    source: 'manual', auto_renew: false, created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z', domains: [], days_left: 90,
    valid_to: '2027-01-01T00:00:00Z', ...overrides,
  }
}

// Kök → Ara → Uç zinciri + zincirsiz tek bir uç sertifika
const CERTS: Certificate[] = [
  cert({ id: 1, name: 'Jumbo Root CA', cert_type: 'root', days_left: 3000 }),
  cert({ id: 2, name: 'Jumbo Issuing CA', cert_type: 'intermediate', parent_id: 1, days_left: 1200 }),
  cert({ id: 3, name: 'www.jumbo.com.tr', cert_type: 'leaf', parent_id: 2, days_left: 20,
         san: 'www.jumbo.com.tr', source: 'vault' }),
  cert({ id: 4, name: 'api.jumbo.local', cert_type: 'leaf', days_left: -5, environment: 'prod' }),
]

// Sunucu /certificates/page yanıtının taklidi: zincir ağacı sırası + derinlik + kök özeti
function mockCertificates(certs: Certificate[]) {
  apiGet.mockImplementation(async (url: string) => {
    if (url === '/certificates/page') {
      const tree = buildTree(certs)
      const rootOf = new Map<number, Certificate>()
      let root: Certificate | null = null
      for (const r of tree) { if (r.depth === 0) root = r.cert; rootOf.set(r.cert.id, root!) }
      const groups: Record<string, { members: number; domain_links: number; worst_days: number | null }> = {}
      for (const r of tree) {
        const g = (groups[rootOf.get(r.cert.id)!.id] ??= { members: 0, domain_links: 0, worst_days: null })
        g.members++
        if (r.cert.days_left != null) g.worst_days = g.worst_days == null ? r.cert.days_left : Math.min(g.worst_days, r.cert.days_left)
      }
      return { data: {
        items: tree.map((r) => ({ cert: r.cert, depth: r.depth, root_id: rootOf.get(r.cert.id)!.id,
                                  root_name: rootOf.get(r.cert.id)!.name,
                                  has_children: certs.some((c) => c.parent_id === r.cert.id) })),
        total: tree.length, page: 0, size: 50, counts: { total: certs.length }, facets: {}, groups,
      } }
    }
    throw new Error(`beklenmeyen istek: ${url}`)
  })
}

describe('Sertifikalar sayfası', () => {
  beforeEach(() => { apiGet.mockReset() })

  it('tablo görünümünde sertifikaları zincir sırasıyla listeler', async () => {
    mockCertificates(CERTS)
    renderPage(<Certificates />, { url: '/certificates' })

    expect(screen.getByRole('heading', { name: 'SSL Sertifikaları' })).toBeInTheDocument()
    await screen.findByText('Jumbo Root CA')

    const rows = screen.getAllByRole('row').slice(1)  // başlık satırı hariç
    expect(rows.map((r) => within(r).getAllByRole('cell')[0].textContent)).toEqual([
      expect.stringContaining('Jumbo Root CA'),
      expect.stringContaining('Jumbo Issuing CA'),
      expect.stringContaining('www.jumbo.com.tr'),
      expect.stringContaining('api.jumbo.local'),
    ])
    expect(screen.getByText('20g kaldı')).toBeInTheDocument()
    expect(screen.getByText('Süresi Doldu (5g)')).toBeInTheDocument()
    expect(apiGet).toHaveBeenCalledWith('/certificates/page', { params: { is_active: true, page: 0, size: 50 } })
  })

  it('kart görünümünde zincirleri gruplar', async () => {
    mockCertificates(CERTS)
    renderPage(<Certificates />, { url: '/certificates?view=cards' })

    expect(await screen.findByText('3 sertifika · 0 domain bağlantısı')).toBeInTheDocument()
    expect(screen.getByText('en kritik: 20g kaldı')).toBeInTheDocument()
    expect(screen.getByText('api.jumbo.local')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('görünüm düğmesiyle tablodan karta geçer', async () => {
    mockCertificates(CERTS)
    const { container } = renderPage(<Certificates />, { url: '/certificates' })
    await screen.findByRole('table')

    // Görünüm düğmelerinin erişilebilir adı yok (tooltip ikonda), bu yüzden value ile seçiliyor.
    await userEvent.click(container.querySelector('button[value="cards"]')!)

    expect(await screen.findByText('3 sertifika · 0 domain bağlantısı')).toBeInTheDocument()
    expect(window.location.search).toContain('view=cards')
  })

  it('liste boşsa boş durum mesajını gösterir', async () => {
    mockCertificates([])
    renderPage(<Certificates />, { url: '/certificates' })

    expect(await screen.findByText(/Henüz sertifika eklenmemiş/)).toBeInTheDocument()
  })

  it('istek başarısız olursa hata ve yeniden dene gösterir', async () => {
    apiGet.mockRejectedValue(new AxiosError('Network Error'))
    renderPage(<Certificates />, { url: '/certificates' })

    expect(await screen.findByText(/Veriler yüklenemedi: Network Error/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Yeniden Dene' })).toBeInTheDocument()
  })

  it('izleyici rolünde yazma düğmelerini göstermez', async () => {
    mockCertificates(CERTS)
    renderPage(<Certificates />, { role: 'viewer', url: '/certificates' })
    await screen.findByText('Jumbo Root CA')

    expect(screen.queryByRole('button', { name: 'Yeni Ekle' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Vault'tan Senkronize Et/ })).not.toBeInTheDocument()
  })

  it('düzenleyici rolünde yazma düğmelerini gösterir', async () => {
    mockCertificates(CERTS)
    renderPage(<Certificates />, { role: 'editor', url: '/certificates' })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Yeni Ekle' })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /Vault'tan Senkronize Et/ })).toBeInTheDocument()
  })
})
