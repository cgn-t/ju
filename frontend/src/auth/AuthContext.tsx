import { useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { TokenResponse } from '../api/types'

interface AuthState {
  token: string | null
  username: string | null
  role: string | null          // atanmış rol: 'admin' | 'editor' | 'viewer' | 'allviewer' | 'none'
  fullName: string | null
  email: string | null
  photo: string | null         // LDAP girişinde AD fotoğrafı (sol menü)
  teamGroups: string[]         // LDAP girişinde ekip grupları, ör. ['SY-BBB'] (sol menü)
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  canEdit: boolean             // admin veya editor → yazma butonları görünür (viewer/allviewer değil)
  isAdmin: boolean             // admin → tam yetki (sil, ayarlar, sahiplik)
  hasNoTeam: boolean           // rol atanmamış ('none') → boş-durum, içerik yok
  isViewerOnly: boolean        // viewer veya allviewer → her şeyi/kendi takımını görür, işlem yapamaz
}

const AuthContext = createContext<AuthState | null>(null)

function readTeams(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem('jumbo_teams') ?? '[]')
    return Array.isArray(v) ? v : []
  } catch { return [] }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [token, setToken] = useState(localStorage.getItem('jumbo_token'))
  const [username, setUsername] = useState(localStorage.getItem('jumbo_username'))
  const [role, setRole] = useState(localStorage.getItem('jumbo_role'))
  const [fullName, setFullName] = useState(localStorage.getItem('jumbo_fullname'))
  const [email, setEmail] = useState(localStorage.getItem('jumbo_email'))
  const [photo, setPhoto] = useState(localStorage.getItem('jumbo_photo'))
  const [teamGroups, setTeamGroups] = useState<string[]>(readTeams)

  const login = async (user: string, password: string) => {
    const { data } = await api.post<TokenResponse>('/auth/login-json', { username: user, password })
    // Aynı sekmede önceki kullanıcının önbelleklenmiş sorguları (özellikle ['auth-me']
    // page_access) yeni kullanıcıya SIZMASIN — staleTime (30sn) boyunca eski rolün
    // gördüğü sayfalar navbar'da yanlışlıkla görünür kalabiliyordu.
    queryClient.clear()
    localStorage.setItem('jumbo_token', data.access_token)
    localStorage.setItem('jumbo_username', data.username)
    localStorage.setItem('jumbo_role', data.role)
    localStorage.setItem('jumbo_fullname', data.full_name ?? '')
    localStorage.setItem('jumbo_email', data.email ?? '')
    // Fotoğraf ve ekip girişte gelir; sayfa yenilense de beklemeden görünsün diye saklanır
    try {
      if (data.photo) localStorage.setItem('jumbo_photo', data.photo); else localStorage.removeItem('jumbo_photo')
    } catch { /* depolama dolu: fotoğraf yalnız bu oturumda */ }
    localStorage.setItem('jumbo_teams', JSON.stringify(data.team_groups ?? []))
    setToken(data.access_token)
    setUsername(data.username)
    setRole(data.role)
    setFullName(data.full_name ?? '')
    setEmail(data.email ?? '')
    setPhoto(data.photo ?? null)
    setTeamGroups(data.team_groups ?? [])
  }

  const logout = () => {
    queryClient.clear()
    for (const k of ['jumbo_token', 'jumbo_username', 'jumbo_role', 'jumbo_fullname', 'jumbo_email', 'jumbo_photo', 'jumbo_teams'])
      localStorage.removeItem(k)
    setToken(null)
    setUsername(null)
    setRole(null)
    setFullName(null)
    setEmail(null)
    setPhoto(null)
    setTeamGroups([])
  }

  return (
    <AuthContext.Provider
      value={{
        token, username, role, fullName, email, photo, teamGroups, login, logout,
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
