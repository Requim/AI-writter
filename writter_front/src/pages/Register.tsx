import { ArrowRightOutlined, BankOutlined, LockOutlined, MailOutlined } from '@ant-design/icons'
import { App, Button, Form, Input } from 'antd'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { AuthLayout } from '@/components/AuthLayout'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/authStore'

interface RegisterValues {
  email: string
  password: string
  tenant_name: string
}

export default function Register() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const accessToken = useAuthStore((state) => state.accessToken)
  const setSession = useAuthStore((state) => state.setSession)
  if (accessToken) return <Navigate to="/" replace />

  const submit = async (values: RegisterValues) => {
    try {
      setSession(await authApi.register(values))
      const invite = params.get('invite')
      navigate(invite ? `/invite/${invite}` : '/', { replace: true })
    } catch {
      message.error('注册失败，请检查邮箱是否已使用')
    }
  }

  return (
    <AuthLayout>
      <div className="auth-form page-enter">
        <span className="eyebrow">新建工作区</span>
        <h2>成立你的编辑部</h2>
        <p>注册后自动成为该工作区 Owner，可再邀请编辑共同创作。</p>
        <Form layout="vertical" onFinish={submit} requiredMark={false}>
          <Form.Item name="email" label="邮箱" rules={[{ required: true }, { type: 'email' }]}>
            <Input size="large" prefix={<MailOutlined />} autoComplete="email" />
          </Form.Item>
          <Form.Item name="tenant_name" label="工作区名称" rules={[{ required: true, min: 2, max: 120 }]}>
            <Input size="large" prefix={<BankOutlined />} placeholder="例如：北岸故事工作室" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, min: 10, message: '至少 10 个字符' }]}>
            <Input.Password size="large" prefix={<LockOutlined />} autoComplete="new-password" />
          </Form.Item>
          <Button htmlType="submit" type="primary" size="large" block icon={<ArrowRightOutlined />} iconPosition="end">
            注册并进入书架
          </Button>
        </Form>
        <div className="auth-switch">已有账号？ <Link to="/login">直接登录</Link></div>
      </div>
    </AuthLayout>
  )
}
