import { ArrowRightOutlined, LockOutlined, MailOutlined } from '@ant-design/icons'
import { App, Button, Form, Input } from 'antd'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { AuthLayout } from '@/components/AuthLayout'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/authStore'

export default function Login() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const accessToken = useAuthStore((state) => state.accessToken)
  const setSession = useAuthStore((state) => state.setSession)
  if (accessToken) return <Navigate to={params.get('next') || '/'} replace />

  const submit = async (values: { email: string; password: string }) => {
    try {
      setSession(await authApi.login(values))
      const invite = params.get('invite')
      navigate(invite ? `/invite/${invite}` : (params.get('next') || '/'), { replace: true })
    } catch {
      message.error('邮箱或密码不正确')
    }
  }

  return (
    <AuthLayout>
      <div className="auth-form page-enter">
        <span className="eyebrow">欢迎回来</span>
        <h2>进入编辑部</h2>
        <p>选择工作区后，只会看到属于该租户的创作资料。</p>
        <Form layout="vertical" onFinish={submit} requiredMark={false}>
          <Form.Item name="email" label="邮箱" rules={[{ required: true }, { type: 'email' }]}>
            <Input size="large" prefix={<MailOutlined />} autoComplete="email" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true }]}>
            <Input.Password size="large" prefix={<LockOutlined />} autoComplete="current-password" />
          </Form.Item>
          <Button htmlType="submit" type="primary" size="large" block icon={<ArrowRightOutlined />} iconPosition="end">
            登录
          </Button>
        </Form>
        <div className="auth-switch">还没有账号？ <Link to="/register">创建编辑部</Link></div>
      </div>
    </AuthLayout>
  )
}
