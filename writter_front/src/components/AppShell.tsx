import type { PropsWithChildren } from 'react'
import {
  BookOutlined,
  LogoutOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { Button, Progress, Select, Tooltip } from 'antd'
import { useEffect, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { authApi, tenantApi } from '@/api/auth'
import { currentTenant, useAuthStore } from '@/stores/authStore'
import type { QuotaUsage } from '@/types/auth'

export function AppShell({ children }: PropsWithChildren) {
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const tenants = useAuthStore((state) => state.tenants)
  const currentTenantId = useAuthStore((state) => state.currentTenantId)
  const refreshToken = useAuthStore((state) => state.refreshToken)
  const switchTenant = useAuthStore((state) => state.switchTenant)
  const clear = useAuthStore((state) => state.clear)
  const [usage, setUsage] = useState<QuotaUsage>()
  const tenant = currentTenant()

  useEffect(() => {
    tenantApi.usage().then(setUsage).catch(() => undefined)
  }, [currentTenantId])

  const changeTenant = (tenantId: string) => {
    switchTenant(tenantId)
    window.location.assign('/')
  }

  const logout = async () => {
    try { if (refreshToken) await authApi.logout(refreshToken) } finally {
      clear()
      navigate('/login', { replace: true })
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <NavLink to="/" className="brand" aria-label="返回书架">
          <span className="brand-mark"><BookOutlined /></span>
          <span><strong>墨间</strong><small>Novel Desk</small></span>
        </NavLink>
        <div className="tenant-console">
          <Select
            aria-label="当前工作区"
            value={currentTenantId}
            onChange={changeTenant}
            options={tenants.map((item) => ({ label: item.name, value: item.id }))}
            popupMatchSelectWidth={false}
          />
          {usage && (
            <Tooltip title={`本月 AI 创作额度 ${usage.used}/${usage.limit}`}>
              <div className="quota-meter">
                <Progress type="circle" size={26} percent={usage.limit ? Math.round(usage.used / usage.limit * 100) : 100} showInfo={false} strokeColor="#176b5b" />
                <span>{usage.remaining}</span>
              </div>
            </Tooltip>
          )}
        </div>
        <nav className="header-nav" aria-label="主导航">
          <NavLink to="/">书架</NavLink>
          {(tenant?.role === 'owner' || tenant?.role === 'admin') && (
            <Tooltip title="编辑部设置"><Button type="text" aria-label="编辑部设置" icon={<SettingOutlined />} onClick={() => navigate('/settings/members')} /></Tooltip>
          )}
          {user?.is_platform_admin && (
            <Tooltip title="租户总台"><Button type="text" aria-label="租户总台" icon={<SafetyCertificateOutlined />} onClick={() => navigate('/admin')} /></Tooltip>
          )}
          <Tooltip title={user?.email}><Button type="text" aria-label="退出登录" icon={<LogoutOutlined />} onClick={() => void logout()} /></Tooltip>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/novels/new')}>新建作品</Button>
        </nav>
      </header>
      <main>{children}</main>
    </div>
  )
}
