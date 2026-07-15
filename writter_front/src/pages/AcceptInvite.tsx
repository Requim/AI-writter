import { CheckCircleOutlined, TeamOutlined } from '@ant-design/icons'
import { App, Button, Result } from 'antd'
import { useEffect, useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { tenantApi } from '@/api/auth'
import { useAuthStore } from '@/stores/authStore'

export default function AcceptInvite() {
  const { token } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const accessToken = useAuthStore((state) => state.accessToken)
  const switchTenant = useAuthStore((state) => state.switchTenant)
  const setTenants = useAuthStore((state) => state.setTenants)
  const [joining, setJoining] = useState(false)
  useEffect(() => { document.title = '接受邀请 · 墨间编辑部' }, [])
  if (!token) return <Navigate to="/" replace />
  if (!accessToken) return <Navigate to={`/login?invite=${encodeURIComponent(token)}`} replace />

  const accept = async () => {
    setJoining(true)
    try {
      const result = await tenantApi.accept(token)
      const tenants = await tenantApi.list()
      setTenants(tenants)
      switchTenant(result.tenant_id)
      message.success('已加入新的编辑部')
      navigate('/', { replace: true })
    } catch {
      message.error('邀请已失效或已被使用')
    } finally {
      setJoining(false)
    }
  }

  return (
    <div className="invite-page">
      <Result
        icon={<TeamOutlined />}
        title="加入一间新的编辑部"
        subTitle="加入后，你可以看到该工作区的共享书架并参与小说创作。"
        extra={<Button type="primary" loading={joining} icon={<CheckCircleOutlined />} onClick={() => void accept()}>接受邀请</Button>}
      />
    </div>
  )
}
