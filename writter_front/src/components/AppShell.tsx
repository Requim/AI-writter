import type { MouseEvent as ReactMouseEvent, PropsWithChildren, ReactNode } from 'react'
import {
  BookOutlined,
  LogoutOutlined,
  PlusOutlined,
  FileSearchOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  FormOutlined,
} from '@ant-design/icons'
import { Button, Progress, Select, Tooltip } from 'antd'
import { NavLink, useLocation, useNavigate } from 'react-router'
import { authApi } from '@/api/auth'
import { currentTenant, useAuthStore } from '@/stores/authStore'
import { useQuota } from '@/stores/quotaStore'
import type { TenantSummary } from '@/types/auth'
import type { NavigationGuard, NavigationGuardOptions } from '@/hooks/useUnsavedChangesGuard'

function runGuarded(
  guard: NavigationGuard | undefined,
  action: () => void | Promise<void>,
  options?: NavigationGuardOptions,
) {
  if (guard) guard(action, options)
  else void action()
}

function GuardedNavLink({
  to,
  guard,
  className,
  children,
  ariaLabel,
  end,
}: PropsWithChildren<{
  to: string
  guard?: NavigationGuard
  className?: string
  ariaLabel?: string
  end?: boolean
}>) {
  const navigate = useNavigate()
  const onClick = (event: ReactMouseEvent<HTMLAnchorElement>) => {
    if (!guard || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    guard(() => navigate(to))
  }
  return <NavLink to={to} end={end} className={className} aria-label={ariaLabel} onClick={onClick}>{children}</NavLink>
}

function WorkspaceNavLink({
  to,
  guard,
  icon,
  label,
  end,
}: {
  to: string
  guard?: NavigationGuard
  icon: ReactNode
  label: string
  end?: boolean
}) {
  return <GuardedNavLink to={to} end={end} guard={guard}>
    <span className="workspace-nav-icon" aria-hidden="true">{icon}</span>
    <span>{label}</span>
  </GuardedNavLink>
}

function WorkspaceNavigation({ guard, role, isPlatformAdmin }: {
  guard?: NavigationGuard; role?: string; isPlatformAdmin?: boolean
}) {
  return <aside className="workspace-sidebar">
    <span className="workspace-nav-label">创作中心</span>
    <nav aria-label="工作区导航">
      <WorkspaceNavLink to="/" end guard={guard} icon={<BookOutlined />} label="作品管理" />
      <WorkspaceNavLink to="/novels/new" guard={guard} icon={<FormOutlined />} label="创建作品" />
      {['owner', 'admin'].includes(role || '') && <GuardedNavLink to="/settings/members" guard={guard}>
        <span className="workspace-nav-icon" aria-hidden="true"><SettingOutlined /></span><span>编辑部设置</span>
      </GuardedNavLink>}
      {['owner', 'admin'].includes(role || '') && <GuardedNavLink to="/research-workbench" guard={guard}>
        <span className="workspace-nav-icon" aria-hidden="true"><FileSearchOutlined /></span><span>写作素材库</span>
      </GuardedNavLink>}
      {isPlatformAdmin && <GuardedNavLink to="/admin" guard={guard}>
        <span className="workspace-nav-icon" aria-hidden="true"><SafetyCertificateOutlined /></span><span>租户总台</span>
      </GuardedNavLink>}
    </nav>
    <div className="workspace-signature"><BookOutlined /><span>墨间 · 作家工作台</span></div>
  </aside>
}

function HeaderNavigation({
  guard,
  role,
  email,
  isPlatformAdmin,
  onLogout,
  minimal,
}: {
  guard?: NavigationGuard
  role?: string
  email?: string
  isPlatformAdmin?: boolean
  onLogout: () => void | Promise<void>
  minimal?: boolean
}) {
  const navigate = useNavigate()
  return (
    <nav className="header-nav" aria-label="主导航">
      <GuardedNavLink to="/" end guard={guard}>书架</GuardedNavLink>
      {!minimal && ['owner', 'admin'].includes(role || '') && (
        <Tooltip title="编辑部设置"><Button type="text" aria-label="编辑部设置" icon={<SettingOutlined />} onClick={() => runGuarded(guard, () => navigate('/settings/members'))} /></Tooltip>
      )}
      {!minimal && isPlatformAdmin && (
        <Tooltip title="租户总台"><Button type="text" aria-label="租户总台" icon={<SafetyCertificateOutlined />} onClick={() => runGuarded(guard, () => navigate('/admin'))} /></Tooltip>
      )}
      <Tooltip title={email}><Button type="text" aria-label="退出登录" icon={<LogoutOutlined />} onClick={() => runGuarded(guard, onLogout)} /></Tooltip>
      {!minimal && <Button type="primary" aria-label="新建作品" icon={<PlusOutlined />} onClick={() => runGuarded(guard, () => navigate('/novels/new'))}>新建作品</Button>}
    </nav>
  )
}

interface TenantConsoleProps {
  tenants: TenantSummary[]
  currentTenantId?: string
  onChange: (tenantId: string) => void
}

function TenantConsole({ tenants, currentTenantId, onChange, minimal }: TenantConsoleProps & { minimal?: boolean }) {
  const { quota: usage } = useQuota()
  if (minimal && tenants.length < 2) return null
  return <div className="tenant-console">
    <Select
      aria-label="当前工作区" value={currentTenantId} onChange={onChange}
      options={tenants.map((item) => ({ label: item.name, value: item.id }))}
      popupMatchSelectWidth={false}
    />
    {!minimal && usage && (usage.unlimited ? (
      <Tooltip title="本月 AI 创作额度：无限">
        <div className="quota-meter unlimited" aria-label="无限额度"><strong>∞</strong><span>无限</span></div>
      </Tooltip>
    ) : (
      <Tooltip title={`本月 AI 创作额度 ${usage.used}/${usage.limit}`}>
        <div className="quota-meter">
          <Progress type="circle" size={26} percent={usage.limit ? Math.round(usage.used / usage.limit * 100) : 100} showInfo={false} strokeColor="#176b5b" />
          <span>{usage.remaining}</span>
        </div>
      </Tooltip>
    ))}
  </div>
}

/** 应用框架可选接收页面离开前的确认逻辑。 */
export function AppShell({ children, onBeforeNavigate, minimal = false }: PropsWithChildren<{ onBeforeNavigate?: NavigationGuard; minimal?: boolean }>) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const inStudio = /^\/novels\/(?!new(?:\/|$))[^/]+/.test(pathname)
  const user = useAuthStore((state) => state.user)
  const tenants = useAuthStore((state) => state.tenants)
  const currentTenantId = useAuthStore((state) => state.currentTenantId)
  const refreshToken = useAuthStore((state) => state.refreshToken)
  const switchTenant = useAuthStore((state) => state.switchTenant)
  const clear = useAuthStore((state) => state.clear)
  const tenant = currentTenant()

  const changeTenant = (tenantId: string) => {
    runGuarded(onBeforeNavigate, () => {
      switchTenant(tenantId)
      window.location.assign('/')
    }, { pageUnload: true })
  }

  const logout = async () => {
    try { if (refreshToken) await authApi.logout(refreshToken) } finally {
      clear()
      navigate('/login', { replace: true })
    }
  }

  return (
    <div className={`app-shell${minimal ? ' app-shell-minimal' : ''}`}>
      <header className="app-header">
        <GuardedNavLink to="/" guard={onBeforeNavigate} className="brand" ariaLabel="返回书架">
          <span className="brand-mark"><BookOutlined /></span>
          <span><strong>墨间</strong><small>作家工作台</small></span>
        </GuardedNavLink>
        <TenantConsole tenants={tenants} currentTenantId={currentTenantId} onChange={changeTenant} minimal={minimal} />
        <HeaderNavigation
          guard={onBeforeNavigate}
          role={tenant?.role}
          email={user?.email}
          isPlatformAdmin={user?.is_platform_admin}
          onLogout={logout}
          minimal={minimal}
        />
      </header>
      <div className={`workspace-layout${inStudio || minimal ? ' workspace-layout-editor' : ''}`}>
        {!inStudio && !minimal && <WorkspaceNavigation guard={onBeforeNavigate} role={tenant?.role} isPlatformAdmin={user?.is_platform_admin} />}
        <main className="workspace-main">{children}</main>
      </div>
    </div>
  )
}
