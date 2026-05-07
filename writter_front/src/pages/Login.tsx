import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Form, Input, Button, message } from 'antd'
import axios from 'axios'

const Login = () => {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const handleLogin = async () => {
    if (!username || !password) {
      message.warning('请输入用户名和密码')
      return
    }
    
    setLoading(true)
    try {
      // TODO: 对接真实登录 API
      const res = await axios.post('/api/v1/auth/login', {
        username,
        password
      })
      
      localStorage.setItem('token', res.data.token)
      localStorage.setItem('user_id', res.data.user_id)
      message.success('登录成功')
      navigate('/')
    } catch (error: any) {
      message.error(error.response?.data?.detail || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 400, margin: '100px auto', padding: '0 20px' }}>
      <Card title="用户登录">
        <Form layout="vertical" onFinish={handleLogin}>
          <Form.Item label="用户名">
            <Input
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="请输入用户名"
            />
          </Form.Item>
          
          <Form.Item label="密码">
            <Input.Password
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="请输入密码"
            />
          </Form.Item>
          
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              登录
            </Button>
          </Form.Item>
          
          <div style={{ textAlign: 'center' }}>
            <a onClick={() => message.info('注册功能开发中')}>没有账号？立即注册</a>
          </div>
        </Form>
      </Card>
    </div>
  )
}

export default Login
