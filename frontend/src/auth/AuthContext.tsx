import { createContext, useContext, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { TokenResponse } from '../api/types'

interface AuthState {
  token: string | null
  username: string | null
  role: string | null          // atanmış rol: 'admin' | 'editor' | 'viewer' | 'allviewer' | 'none'
  fullName: string | null
  email: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  canEdit: boolean             // admin veya editor → yazma butonları görünür (viewer/allviewer değil)
  isAdmin: boolean             // admin → tam yetki (sil, ayarlar, sahiplik)
  hasNoTeam: boolean           // rol atanmamış ('none') → boş-durum, içerik yok
  isViewerOnly: boolean        // viewer veya allviewer → her şeyi/kendi takımını görür, işlem yapamaz
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(localStorage.getItem('jumbo_token'))
  const [username, setUsername] = useState(localStorage.getItem('jumbo_username'))
  const [role, setRole] = useState(localStorage.getItem('jumbo_role'))
  const [fullName, setFullName] = useState(localStorage.getItem('jumbo_fullname'))
  const [email, setEmail] = useState(localStorage.getItem('jumbo_email'))

  const login = async (user: string, password: string) => {
    const { data } = await api.post<TokenResponse>('/auth/login-json', { username: user, password })
    localStorage.setItem('jumbo_token', data.access_token)
    localStorage.setItem('jumbo_username', data.username)
    localStorage.setItem('jumbo_role', data.role)
    localStorage.setItem('jumbo_fullname', data.full_name ?? '')
    localStorage.setItem('jumbo_email', data.email ?? '')
    setToken(data.access_token)
    setUsername(data.username)
    setRole(data.role)
    setFullName(data.full_name ?? '')
    setEmail(data.email ?? '')
  }

  const logout = () => {
    for (const k of ['jumbo_token', 'jumbo_username', 'jumbo_role', 'jumbo_fullname', 'jumbo_email'])
      localStorage.removeItem(k)
    setToken(null)
    setUsername(null)
    setRole(null)
    setFullName(null)
    setEmail(null)
  }

  return (
    <AuthContext.Provider
      value={{
        token, username, role, fullName, email, login, logout,
        canEdit: role === 'admin' || role === 'editor',
        isAdmin: role === 'admin',
        hasNoTeam: role === 'none',
        isViewerOnly: role === 'viewer',
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth, AuthProvider içinde kullanılmalı')
  return ctx
}
