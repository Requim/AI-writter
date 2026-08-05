import axios from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { refreshSession } from './session'
import { useAuthStore } from '@/stores/authStore'
import type { AuthSession } from '@/types/auth'

const session: AuthSession = {
  access_token: 'fresh-access', refresh_token: 'fresh-refresh', token_type: 'bearer', expires_in: 3600,
  user: { id: 'user-1', email: 'writer@example.com', is_platform_admin: false, status: 'active' },
  tenants: [{ id: 'tenant-1', name: '编辑部', slug: 'desk', role: 'owner', status: 'active', ai_enabled: true, monthly_generation_limit: 30, monthly_generation_unlimited: false }],
}

describe('refreshSession', () => {
  afterEach(() => { vi.restoreAllMocks(); useAuthStore.getState().clear() })

  it('shares one refresh request across concurrent callers', async () => {
    useAuthStore.setState({ refreshToken: 'old-refresh' })
    const post = vi.spyOn(axios, 'post').mockResolvedValue({ data: session })
    const first = refreshSession()
    const second = refreshSession()
    await expect(Promise.all([first, second])).resolves.toEqual([session, session])
    expect(post).toHaveBeenCalledTimes(1)
    expect(useAuthStore.getState().accessToken).toBe('fresh-access')
  })
})
