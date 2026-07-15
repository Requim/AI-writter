import { ApartmentOutlined, PauseCircleOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { App, Button, InputNumber, Switch, Table, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { adminApi } from '@/api/auth'
import { AppShell } from '@/components/AppShell'
import type { AdminTenant, AdminUser } from '@/types/auth'

export default function PlatformAdmin() {
  const { message } = App.useApp()
  const [tenants, setTenants] = useState<AdminTenant[]>([])
  const [users, setUsers] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState(true)
  const load = async () => {
    setLoading(true)
    try {
      const [tenantData, userData] = await Promise.all([adminApi.tenants(), adminApi.users()])
      setTenants(tenantData)
      setUsers(userData)
    } finally { setLoading(false) }
  }
  useEffect(() => { queueMicrotask(() => void load()) }, [])

  const patch = async (tenant: AdminTenant, values: Parameters<typeof adminApi.updateTenant>[1]) => {
    await adminApi.updateTenant(tenant.id, values)
    message.success('租户策略已更新')
    await load()
  }

  const patchUser = async (user: AdminUser) => {
    await adminApi.updateUser(user.id, user.status === 'active' ? 'suspended' : 'active')
    message.success('账号状态已更新')
    await load()
  }

  return (
    <AppShell>
      <div className="settings-page admin-page page-enter">
        <header className="settings-heading">
          <span className="eyebrow">Platform Control</span>
          <h1>租户总台</h1>
          <p>查看本月 AI 用量，调整额度，并暂停异常工作区。</p>
        </header>
        <section className="admin-metrics">
          <div><span>租户总数</span><strong>{tenants.length}</strong></div>
          <div><span>活跃租户</span><strong>{tenants.filter((tenant) => tenant.status === 'active').length}</strong></div>
          <div><span>本月任务</span><strong>{tenants.reduce((sum, tenant) => sum + tenant.usage, 0)}</strong></div>
        </section>
        <section className="member-section">
          <div className="section-title"><ApartmentOutlined /><div><h2>租户列表</h2><p>额度按 Asia/Shanghai 自然月统计</p></div></div>
          <Table
            loading={loading}
            rowKey="id"
            dataSource={tenants}
            scroll={{ x: 900 }}
            pagination={false}
            columns={[
              { title: '工作区', dataIndex: 'name', render: (name: string, tenant: AdminTenant) => <div><strong>{name}</strong><small>{tenant.slug}</small></div> },
              { title: '成员', dataIndex: 'member_count', width: 80 },
              { title: '本月用量', width: 120, render: (_: unknown, tenant: AdminTenant) => `${tenant.usage} / ${tenant.monthly_generation_limit}` },
              { title: '额度', width: 120, render: (_: unknown, tenant: AdminTenant) => <InputNumber min={0} max={100000} value={tenant.monthly_generation_limit} onChange={(value) => value !== null && void patch(tenant, { monthly_generation_limit: value })} /> },
              { title: 'AI', width: 80, render: (_: unknown, tenant: AdminTenant) => <Switch checked={tenant.ai_enabled} onChange={(checked) => void patch(tenant, { ai_enabled: checked })} /> },
              { title: '状态', width: 100, render: (_: unknown, tenant: AdminTenant) => <Tag color={tenant.status === 'active' ? 'green' : 'red'}>{tenant.status}</Tag> },
              { title: '', width: 120, render: (_: unknown, tenant: AdminTenant) => <Button danger={tenant.status === 'active'} icon={tenant.status === 'active' ? <PauseCircleOutlined /> : <PlayCircleOutlined />} onClick={() => void patch(tenant, { status: tenant.status === 'active' ? 'suspended' : 'active' })}>{tenant.status === 'active' ? '暂停' : '恢复'}</Button> },
            ]}
          />
        </section>
        <section className="member-section">
          <div className="section-title"><ApartmentOutlined /><div><h2>账号目录</h2><p>停用后所有 Access 与 Refresh 会话立即失效</p></div></div>
          <Table
            loading={loading}
            rowKey="id"
            dataSource={users}
            pagination={false}
            columns={[
              { title: '邮箱', dataIndex: 'email' },
              { title: '租户数', dataIndex: 'tenant_count', width: 90 },
              { title: '身份', width: 120, render: (_: unknown, user: AdminUser) => user.is_platform_admin ? <Tag color="gold">平台管理员</Tag> : <Tag>用户</Tag> },
              { title: '状态', width: 100, render: (_: unknown, user: AdminUser) => <Tag color={user.status === 'active' ? 'green' : 'red'}>{user.status}</Tag> },
              { title: '', width: 110, render: (_: unknown, user: AdminUser) => user.is_platform_admin ? null : <Button danger={user.status === 'active'} onClick={() => void patchUser(user)}>{user.status === 'active' ? '停用' : '恢复'}</Button> },
            ]}
          />
        </section>
      </div>
    </AppShell>
  )
}
