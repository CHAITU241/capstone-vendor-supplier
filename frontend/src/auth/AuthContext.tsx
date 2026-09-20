import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { PortalSession } from '../api/types'

const STORAGE_KEY = 'vendorlens.session'

function initialSession(): PortalSession | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value ? JSON.parse(value) as PortalSession : null
  } catch { return null }
}

type AuthState = {
  session: PortalSession | null
  setSession: (session: PortalSession) => void
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, updateSession] = useState<PortalSession | null>(initialSession)

  useEffect(() => {
    if (!session?.token) return
    void api.session().catch(() => {
      localStorage.removeItem(STORAGE_KEY)
      updateSession(null)
    })
  }, [session?.token])

  function setSession(value: PortalSession) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
    updateSession(value)
  }

  async function signOut() {
    try { await api.logout() } catch { /* Expired sessions can still be cleared locally. */ }
    localStorage.removeItem(STORAGE_KEY)
    updateSession(null)
  }

  return <AuthContext.Provider value={{ session, setSession, signOut }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('AuthProvider is missing')
  return context
}
