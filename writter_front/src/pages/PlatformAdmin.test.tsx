import { App } from 'antd'
import type { ReactNode } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { tenantsMock, updateTenantMock, usersMock } = vi.hoisted(() => ({
  tenantsMock: vi.fn(), updateTenantMock: vi.fn(), usersMock: vi.fn(),
}))

vi.mock('@/api/auth', () => ({
  adminApi: { tenants: tenantsMock, users: usersMock, updateTenant: updateTenantMock, updateUser: vi.fn() },
}))
vi.mock('@/components/AppShell', () => ({ AppShell: ({ children }: { children: ReactNode }) => children }))

import PlatformAdmin from './PlatformAdmin'

afterEach(cleanup)

describe('PlatformAdmin planning policy', () => {
  beforeEach(() => {
    updateTenantMock.mockReset().mockResolvedValue({})
    usersMock.mockReset().mockResolvedValue([])
    tenantsMock.mockReset().mockResolvedValue([{
      id: 'tenant-1', name: '测试编辑部', slug: 'test-desk', status: 'active', ai_enabled: true,
      monthly_generation_limit: 30, monthly_generation_unlimited: false, member_count: 2, usage: 7,
      novel_planning_v1_enabled: true, novel_planning_v1_effective: false,
      novel_planning_v1_globally_enabled: false,
    }])
  })

  it('shows requested/effective state and updates only the tenant request flag', async () => {
    render(<App><PlatformAdmin /></App>)
    expect(await screen.findByText('整书规划全局开关已关闭')).toBeInTheDocument()
    expect(screen.getByText('全局关闭')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('switch', { name: '测试编辑部整书规划' }))
    await waitFor(() => expect(updateTenantMock).toHaveBeenCalledWith(
      'tenant-1', { novel_planning_v1_enabled: false },
    ))
  })
})
