import { beforeEach, describe, expect, it, vi } from 'vitest'

const usageMock = vi.hoisted(() => vi.fn())

vi.mock('@/api/auth', () => ({ tenantApi: { usage: usageMock } }))

import { useAuthStore } from './authStore'
import { estimatedQuotaCost, refreshQuota, useQuotaStore } from './quotaStore'

describe('quotaStore', () => {
  beforeEach(() => {
    usageMock.mockReset()
    useQuotaStore.getState().reset()
    useAuthStore.setState({ currentTenantId: 'tenant-1' })
  })

  it('shares one in-flight quota request for the current tenant', async () => {
    usageMock.mockResolvedValue({
      used: 2, limit: 30, remaining: 28, unlimited: false, ai_enabled: true, period_start: '2026-08-01',
    })
    const first = refreshQuota()
    const second = refreshQuota()
    await Promise.all([first, second])
    expect(usageMock).toHaveBeenCalledTimes(1)
    expect(useQuotaStore.getState().quota?.remaining).toBe(28)
  })

  it('includes startup and every planned chapter in the estimate', () => {
    expect(estimatedQuotaCost(3)).toBe(4)
    expect(estimatedQuotaCost(undefined)).toBe(13)
  })
})
