import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { api } from '../api/client'
import type { PortalSession } from '../api/types'

type PortalRole = PortalSession['role']
type Sessions = Partial<Record<PortalRole, PortalSession>>

const LEGACY_STORAGE_KEY = 'vendorlens.session'
const storageKey = (role: PortalRole) => `vendorlens.session.${role}`

function readSession(key: string): PortalSession | undefined {
  try {
    const value = localStorage.getItem(key)
    return value ? JSON.parse(value) as PortalSession : undefined
  } catch { return undefined }
}

function initialSessions(): Sessions {
  const sessions: Sessions = {}
  for (const role of ['supplier', 'reviewer', 'admin'] as const) {
    const saved = readSession(storageKey(role))
    if (saved?.role === role) sessions[role] = saved
  }
  const legacy = readSession(LEGACY_STORAGE_KEY)
  if (legacy?.role && !sessions[legacy.role]) {
    sessions[legacy.role] = legacy
    localStorage.setItem(storageKey(legacy.role), JSON.stringify(legacy))
  }
  localStorage.removeItem(LEGACY_STORAGE_KEY)
  return sessions
}

function roleForPath(pathname: string): PortalRole | undefined {
  if (pathname.startsWith('/supplier')) return 'supplier'
  if (pathname.startsWith('/review')) return 'reviewer'
  if (pathname.startsWith('/admin')) return 'admin'
  return undefined
}

type AuthState = {
  session: PortalSession | null
  getSession: (role: PortalRole) => PortalSession | null
  setSession: (session: PortalSession) => void
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const location = useLocation()
  const [sessions, setSessions] = useState<Sessions>(initialSessions)
  const routeRole = roleForPath(location.pathname)
  const session = routeRole ? sessions[routeRole] ?? null : null

  useEffect(() => {
    if (!routeRole || !session?.token) return
    void api.session(routeRole).catch(() => {
      localStorage.removeItem(storageKey(routeRole))
      setSessions((current) => ({ ...current, [routeRole]: undefined }))
    })
  }, [routeRole, session?.token])

  const value = useMemo<AuthState>(() => ({
    session,
    getSession: (role) => sessions[role] ?? null,
    setSession: (nextSession) => {
      localStorage.setItem(storageKey(nextSession.role), JSON.stringify(nextSession))
      setSessions((current) => ({ ...current, [nextSession.role]: nextSession }))
    },
    signOut: async () => {
      if (!session) return
      try { await api.logout(session.role) } catch { /* Expired sessions can still be cleared locally. */ }
      localStorage.removeItem(storageKey(session.role))
      setSessions((current) => ({ ...current, [session.role]: undefined }))
    },
  }), [session, sessions])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('AuthProvider is missing')
  return context
}
