import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AuthSession, AuthUser, TenantSummary } from '@/types/auth'

interface AuthState {
  accessToken?: string
  refreshToken?: string
  user?: AuthUser
  tenants: TenantSummary[]
  currentTenantId?: string
  setSession: (session: AuthSession) => void
  setTenants: (tenants: TenantSummary[]) => void
  switchTenant: (tenantId: string) => void
  clear: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      tenants: [],
      setSession: (session) => set((state) => ({
        accessToken: session.access_token,
        refreshToken: session.refresh_token,
        user: session.user,
        tenants: session.tenants,
        currentTenantId: session.tenants.some((tenant) => tenant.id === state.currentTenantId)
          ? state.currentTenantId
          : session.tenants[0]?.id,
      })),
      setTenants: (tenants) => set((state) => ({
        tenants,
        currentTenantId: tenants.some((tenant) => tenant.id === state.currentTenantId)
          ? state.currentTenantId
          : tenants[0]?.id,
      })),
      switchTenant: (currentTenantId) => set({ currentTenantId }),
      clear: () => set({
        accessToken: undefined,
        refreshToken: undefined,
        user: undefined,
        tenants: [],
        currentTenantId: undefined,
      }),
    }),
    {
      name: 'novel-writer-auth',
      partialize: ({ accessToken, refreshToken, user, tenants, currentTenantId }) => ({
        accessToken,
        refreshToken,
        user,
        tenants,
        currentTenantId,
      }),
    },
  ),
)

export function currentTenant(): TenantSummary | undefined {
  const state = useAuthStore.getState()
  return state.tenants.find((tenant) => tenant.id === state.currentTenantId)
}
