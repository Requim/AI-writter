import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/stores/authStore'
import { redirectToLogin, refreshSession } from './session'

interface RetryConfig extends InternalAxiosRequestConfig {
  _retry?: boolean
}

export const apiClient = axios.create({
  baseURL: '/api',
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
})

apiClient.interceptors.request.use((config) => {
  const { accessToken, currentTenantId } = useAuthStore.getState()
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`
  if (currentTenantId) config.headers['X-Tenant-ID'] = currentTenantId
  return config
})

async function retryAfterRefresh(error: AxiosError): Promise<unknown> {
  const config = error.config as RetryConfig | undefined
  if (!config || error.response?.status !== 401) return Promise.reject(error)
  if (config._retry) {
    redirectToLogin()
    return Promise.reject(error)
  }
  if (config.url?.includes('/v1/auth/')) return Promise.reject(error)
  config._retry = true
  try {
    const session = await refreshSession()
    config.headers.Authorization = `Bearer ${session.access_token}`
    return apiClient(config)
  } catch (refreshError) {
    redirectToLogin()
    return Promise.reject(refreshError)
  }
}

apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => axios.isAxiosError(error)
    ? retryAfterRefresh(error)
    : Promise.reject(error),
)
