import { CopyOutlined, DeleteOutlined, LinkOutlined, SwapOutlined, TeamOutlined } from '@ant-design/icons'
import { App, Button, Form, Input, Select, Table, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { AppShell } from '@/components/AppShell'
import { authApi, tenantApi } from '@/api/auth'
import { currentTenant, useAuthStore } from '@/stores/authStore'
import type { TenantMember, TenantRole } from '@/types/auth'

export default function TenantSettings() {
  const { message, modal } = App.useApp()
  const user = useAuthStore((state) => state.user)
  const setTenants = useAuthStore((state) => state.setTenants)
  const tenant = currentTenant()
  const [members, setMembers] = useState<TenantMember[]>([])
  const [name, setName] = useState(tenant?.name || '')
  const [inviteRole, setInviteRole] = useState<'admin' | 'member'>('member')
  const [inviteLink, setInviteLink] = useState('')

  const load = async () => setMembers(await tenantApi.members())
  useEffect(() => { queueMicrotask(() => void load()) }, [])
  if (!tenant) return null
  const canManage = tenant.role === 'owner' || tenant.role === 'admin'

  const saveName = async () => {
    await tenantApi.update(name)
    const tenants = await tenantApi.list()
    setTenants(tenants)
    message.success('工作区名称已更新')
  }

  const createInvite = async () => {
    const result = await tenantApi.invite(tenant.role === 'admin' ? 'member' : inviteRole)
    setInviteLink(`${window.location.origin}${result.invite_path}`)
  }

  const copyInvite = async () => {
    await navigator.clipboard.writeText(inviteLink)
    message.success('邀请链接已复制')
  }

  const updateRole = async (member: TenantMember, role: Exclude<TenantRole, 'owner'>) => {
    await tenantApi.updateRole(member.user_id, role)
    await load()
  }

  const remove = (member: TenantMember) => modal.confirm({
    title: `移除 ${member.email}？`,
    content: '该账号将立即失去当前工作区和书稿的访问权限。',
    okText: '移除成员',
    okButtonProps: { danger: true },
    cancelText: '取消',
    onOk: async () => { await tenantApi.removeMember(member.user_id); await load() },
  })

  const transfer = (member: TenantMember) => modal.confirm({
    title: `将 Owner 转让给 ${member.email}？`,
    content: '转让后你的角色将变为 Admin，该操作会立即生效。',
    okText: '确认转让',
    cancelText: '取消',
    onOk: async () => {
      await tenantApi.transferOwnership(member.user_id)
      setTenants(await tenantApi.list())
      window.location.reload()
    },
  })

  const changePassword = async (values: { current_password: string; new_password: string }) => {
    await authApi.changePassword(values)
    message.success('密码已更新，请重新登录')
    useAuthStore.getState().clear()
    window.location.assign('/login')
  }

  return (
    <AppShell>
      <div className="settings-page page-enter">
        <header className="settings-heading">
          <span className="eyebrow">Tenant Administration</span>
          <h1>编辑部设置</h1>
          <p>管理当前工作区的名称、成员角色与一次性邀请链接。</p>
        </header>

        <section className="settings-band">
          <div><h2>工作区档案</h2><p>租户标识：{tenant.slug}</p></div>
          <div className="settings-inline">
            <Input value={name} maxLength={120} disabled={tenant.role !== 'owner'} onChange={(event) => setName(event.target.value)} />
            {tenant.role === 'owner' && <Button type="primary" onClick={() => void saveName()}>保存名称</Button>}
          </div>
        </section>

        {canManage && (
          <section className="settings-band invite-band">
            <div><h2>邀请新成员</h2><p>链接 7 天内有效且只能使用一次。</p></div>
            <div className="invite-builder">
              {tenant.role === 'owner' && (
                <Select value={inviteRole} onChange={setInviteRole} options={[{ label: 'Member', value: 'member' }, { label: 'Admin', value: 'admin' }]} />
              )}
              <Button icon={<LinkOutlined />} onClick={() => void createInvite()}>生成邀请链接</Button>
              {inviteLink && <Input value={inviteLink} readOnly addonAfter={<Button type="text" icon={<CopyOutlined />} onClick={() => void copyInvite()} aria-label="复制邀请链接" />} />}
            </div>
          </section>
        )}

        <section className="member-section">
          <div className="section-title"><TeamOutlined /><div><h2>成员名册</h2><p>{members.length} 位成员共享当前书架</p></div></div>
          <Table
            rowKey="user_id"
            dataSource={members}
            pagination={false}
            columns={[
              { title: '账号', dataIndex: 'email' },
              {
                title: '角色', dataIndex: 'role', width: 170,
                render: (role: TenantRole, member: TenantMember) => tenant.role === 'owner' && role !== 'owner'
                  ? <Select value={role} onChange={(value) => void updateRole(member, value)} options={[{ label: 'Admin', value: 'admin' }, { label: 'Member', value: 'member' }]} />
                  : <Tag color={role === 'owner' ? 'gold' : role === 'admin' ? 'green' : undefined}>{role.toUpperCase()}</Tag>,
              },
              { title: '状态', dataIndex: 'status', width: 100, render: (status: string) => status === 'active' ? '正常' : '已停用' },
              {
                title: '', width: 54,
                render: (_value: unknown, member: TenantMember) => member.user_id !== user?.id && member.role !== 'owner'
                  ? <div className="member-actions">
                      {tenant.role === 'owner' && <Button type="text" icon={<SwapOutlined />} aria-label="转让 Owner" onClick={() => transfer(member)} />}
                      {canManage && (tenant.role === 'owner' || member.role === 'member') && <Button danger type="text" icon={<DeleteOutlined />} aria-label="移除成员" onClick={() => remove(member)} />}
                    </div>
                  : null,
              },
            ]}
          />
        </section>
        <section className="settings-band account-band">
          <div><h2>账号安全</h2><p>修改密码会撤销当前账号的所有刷新会话。</p></div>
          <Form layout="inline" onFinish={changePassword} requiredMark={false}>
            <Form.Item name="current_password" rules={[{ required: true }]}><Input.Password placeholder="当前密码" autoComplete="current-password" /></Form.Item>
            <Form.Item name="new_password" rules={[{ required: true, min: 10 }]}><Input.Password placeholder="新密码（至少 10 位）" autoComplete="new-password" /></Form.Item>
            <Button htmlType="submit">更新密码</Button>
          </Form>
        </section>
      </div>
    </AppShell>
  )
}
