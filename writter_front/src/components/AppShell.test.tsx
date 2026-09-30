import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { ConfigProvider, theme } from 'antd'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppShell } from './AppShell'
import { workbenchTheme } from '@/theme'
import type { NavigationGuard } from '@/hooks/useUnsavedChangesGuard'

const { tenant } = vi.hoisted(() => ({ tenant: { id: 'test-tenant', name: '测试编辑部', role: 'owner' } }))
vi.mock('@/stores/quotaStore', () => ({ useQuota: () => ({ quota: undefined }) }))
vi.mock('@/stores/authStore', () => ({
  currentTenant: () => tenant,
  useAuthStore: (select: (state: unknown) => unknown) => select({
    user: { email: 'writer@example.test', is_platform_admin: false },
    tenants: [tenant], currentTenantId: tenant.id, clear: vi.fn(), switchTenant: vi.fn(),
  }),
}))

afterEach(() => { cleanup(); tenant.role = 'owner' })

function mount(path = '/', guard?: NavigationGuard) {
  const router = createMemoryRouter([{
    path: '*', element: <ConfigProvider theme={workbenchTheme}>
      <AppShell onBeforeNavigate={guard}><div>稿件</div></AppShell>
    </ConfigProvider>,
  }], { initialEntries: [path] })
  render(<RouterProvider router={router} />)
  return router
}

describe('统一工作台导航', () => {
  it('keeps exact active routes and navigates to creation', async () => {
    const router = mount()
    const nav = within(screen.getByRole('navigation', { name: '工作区导航' }))
    expect(nav.getByRole('link', { name: '作品管理' })).toBeInTheDocument()
    expect(nav.getByRole('link', { name: /作品管理/ })).toHaveAttribute('aria-current', 'page')
    fireEvent.click(nav.getByRole('link', { name: /创建作品/ }))
    expect(router.state.location.pathname).toBe('/novels/new')
    expect(await nav.findByRole('link', { name: /创建作品/ })).toHaveAttribute('aria-current', 'page')
    expect(nav.getByRole('link', { name: /作品管理/ })).not.toHaveAttribute('aria-current')
  })

  it('preserves the unsaved manuscript guard for sidebar navigation', () => {
    const guard = vi.fn()
    const router = mount('/novels/new', guard)
    fireEvent.click(within(screen.getByRole('navigation', { name: '工作区导航' })).getByRole('link', { name: /作品管理/ }))
    expect(guard).toHaveBeenCalledOnce()
    expect(router.state.location.pathname).toBe('/novels/new')
  })

  it('keeps studio width for chapter editing', () => {
    mount('/novels/book-1')
    expect(screen.queryByRole('navigation', { name: '工作区导航' })).not.toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: '主导航' })).toBeInTheDocument()
  })

  it('does not expose owner navigation to members', () => {
    tenant.role = 'member'
    mount()
    expect(screen.queryByRole('link', { name: /编辑部设置|租户总台/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '编辑部设置' })).not.toBeInTheDocument()
  })

  it('uses the same primary color in Ant Design and the application theme', () => {
    function Probe() {
      const { token } = theme.useToken()
      return <output aria-label="主色">{token.colorPrimary}</output>
    }
    render(<ConfigProvider theme={workbenchTheme}><Probe /></ConfigProvider>)
    expect(screen.getByLabelText('主色')).toHaveTextContent('#e64b32')
  })
})
