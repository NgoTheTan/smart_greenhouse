import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, getToken, setToken } from './api'
import type { User } from './types'

interface AuthContextValue {
  token: string | null
  user: User | null
  isLoading: boolean
  isAuthenticated: boolean
  canOperate: boolean
  isOwner: boolean
  loginWithToken: (token: string) => Promise<User>
  logout: () => void
  refreshMe: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [token, setTokenState] = useState<string | null>(() => getToken())
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(() => Boolean(getToken()))

  const logout = useCallback(() => {
    setToken(null)
    setTokenState(null)
    setUser(null)
    setIsLoading(false)
    queryClient.clear()
  }, [queryClient])

  const fetchMe = useCallback(async () => {
    const activeToken = getToken()
    if (!activeToken) {
      setUser(null)
      setIsLoading(false)
      return
    }
    setIsLoading(true)
    try {
      const me = await api<User>('/me')
      setUser(me)
    } catch {
      setToken(null)
      setTokenState(null)
      setUser(null)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetchMe()
  }, [fetchMe])

  useEffect(() => {
    const onUnauthorized = () => {
      logout()
    }
    window.addEventListener('gh:unauthorized', onUnauthorized)
    return () => window.removeEventListener('gh:unauthorized', onUnauthorized)
  }, [logout])

  const loginWithToken = useCallback(async (newToken: string): Promise<User> => {
    setToken(newToken)
    setTokenState(newToken)
    setIsLoading(true)
    try {
      const me = await api<User>('/me')
      setUser(me)
      return me
    } catch (err) {
      setToken(null)
      setTokenState(null)
      setUser(null)
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      user,
      isLoading,
      isAuthenticated: Boolean(token && user),
      canOperate: Boolean(user),
      isOwner: Boolean(user),
      loginWithToken,
      logout,
      refreshMe: fetchMe,
    }),
    [token, user, isLoading, loginWithToken, logout, fetchMe],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth phải được dùng bên trong AuthProvider')
  return ctx
}
