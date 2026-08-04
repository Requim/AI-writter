import { useEffect } from 'react'
import { create } from 'zustand'
import { tenantApi } from '@/api/auth'
import type { QuotaUsage } from '@/types/auth'
import { useAuthStore } from './authStore'

interface QuotaState {
  tenantId?: string
  quota?: QuotaUsage
  loading: boolean
  begin: (tenantId: string) => void
  resolve: (tenantId: string, quota?: QuotaUsage) => void
  reset: () => void
}

export const useQuotaStore = create<QuotaState>((set) => ({
  loading: false,
  begin: (tenantId) => set({ tenantId, quota: undefined, loading: true }),
  resolve: (tenantId, quota) => set((state) => (
    state.tenantId === tenantId ? { ...state, quota, loading: false } : state
  )),
  reset: () => set({ tenantId: undefined, quota: undefined, loading: false }),
}))

let pendingTenantId: string | undefined
let pendingRequest: Promise<void> | undefined

function finishRequest(request: Promise<void>): void {
  if (pendingRequest !== request) return
  pendingRequest = undefined
  pendingTenantId = undefined
}

export function refreshQuota(): Promise<void> {
  const tenantId = useAuthStore.getState().currentTenantId
  if (!tenantId) {
    useQuotaStore.getState().reset()
    return Promise.resolve()
  }
  if (pendingRequest && pendingTenantId === tenantId) return pendingRequest
  useQuotaStore.getState().begin(tenantId)
  const request = tenantApi.usage()
    .then((quota) => useQuotaStore.getState().resolve(tenantId, quota))
    .catch(() => useQuotaStore.getState().resolve(tenantId))
  pendingTenantId = tenantId
  pendingRequest = request
  void request.finally(() => finishRequest(request))
  return request
}

export function useQuota() {
  const tenantId = useAuthStore((state) => state.currentTenantId)
  const state = useQuotaStore()
  useEffect(() => { void refreshQuota() }, [tenantId])
  return {
    quota: state.tenantId === tenantId ? state.quota : undefined,
    loading: Boolean(tenantId) && (state.tenantId !== tenantId || state.loading),
    refresh: refreshQuota,
  }
}

export function estimatedQuotaCost(chapters: number | undefined): number {
  const count = typeof chapters === 'number' && Number.isFinite(chapters)
    ? Math.max(1, Math.floor(chapters)) : 1
  return count + 1
}
