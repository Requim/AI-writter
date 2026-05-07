import axios from 'axios'
import type { AxiosInstance, AxiosRequestConfig } from 'axios'
import { message } from 'antd'

// 创建 Axios 实例
const apiClient: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 600000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
apiClient.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response) {
      const { status, data } = error.response
      if (status === 401) {
        localStorage.removeItem('token')
        window.location.href = '/login'
        message.error('请先登录')
      } else if (status === 404) {
        // 404 由调用方自行处理，不弹出全局提示
      } else {
        message.error(data.detail || '请求失败')
      }
    } else {
      message.error('网络错误，请检查后端是否启动')
    }
    return Promise.reject(error)
  }
)

export default apiClient
