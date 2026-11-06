import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { renderPage } from '../test/render'
import ChangePasswordDialog from './ChangePasswordDialog'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
const apiPost = vi.mocked(api.post)

const fill = async (cur: string, next: string, again: string) => {
  const u = userEvent.setup()
  if (cur) await u.type(screen.getByLabelText(/Mevcut şifre/), cur)
  if (next) await u.type(screen.getByLabelText(/^Yeni şifre\s*\*?$/), next)
  if (again) await u.type(screen.getByLabelText(/Yeni şifre \(tekrar\)/), again)
  await u.click(screen.getByRole('button', { name: 'Şifreyi Değiştir' }))
}

describe('ChangePasswordDialog', () => {
  beforeEach(() => { apiPost.mockReset() })

  it('yeni şifreler aynı değilse göndermez', async () => {
    renderPage(<ChangePasswordDialog open onClose={() => {}} />)
    await fill('admin', 'yeni-sifre-1', 'yeni-sifre-2')
    expect(screen.getByText('Yeni şifreler aynı değil')).toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('kısa şifreyi göndermez', async () => {
    renderPage(<ChangePasswordDialog open onClose={() => {}} />)
    await fill('admin', 'kisa', 'kisa')
    expect(screen.getByText('En az 8 karakter')).toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('doğru girişte gönderir ve kapanır', async () => {
    apiPost.mockResolvedValue({ data: { message: 'ok' } })
    const onClose = vi.fn()
    renderPage(<ChangePasswordDialog open onClose={onClose} />)
    await fill('admin', 'yeni-sifre-1', 'yeni-sifre-1')
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(apiPost).toHaveBeenCalledWith('/auth/change-password',
      { current_password: 'admin', new_password: 'yeni-sifre-1' })
  })

  it('sunucu hatasını gösterir', async () => {
    apiPost.mockRejectedValue(Object.assign(new Error('400'), { isAxiosError: true, response: { data: { detail: 'Mevcut şifre hatalı.' } } }))
    renderPage(<ChangePasswordDialog open onClose={() => {}} />)
    await fill('yanlis', 'yeni-sifre-1', 'yeni-sifre-1')
    expect(await screen.findByText('Mevcut şifre hatalı.')).toBeInTheDocument()
  })
})
