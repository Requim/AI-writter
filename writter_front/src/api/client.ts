import axios, { type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/stores/authStore'
import type { AuthSession } from '@/types/auth'

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

let refreshPromise: Promise<AuthSession> | undefined

async function refreshSession(): Promise<AuthSession> {
  const refreshToken = useAuthStore.getState().refreshToken
  if (!refreshToken) throw new Error('No refresh token')
  refreshPromise ??= axios
    .post<AuthSession>('/api/v1/auth/refresh', { refresh_token: refreshToken })
    .then(({ data }) => {
      useAuthStore.getState().setSession(data)
      return data
    })
    .finally(() => { refreshPromise = undefined })
  return refreshPromise
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: unknown) => {
    if (!axios.isAxiosError(error) || !error.config || error.response?.status !== 401) {
      return Promise.reject(error)
    }
    const config = error.config as RetryConfig
    if (config._retry || config.url?.includes('/v1/auth/')) {
      return Promise.reject(error)
    }
    config._retry = true
    try {
      const session = await refreshSession()
      config.headers.Authorization = `Bearer ${session.access_token}`
      return apiClient(config)
    } catch (refreshError) {
      useAuthStore.getState().clear()
      if (!window.location.pathname.startsWith('/login')) window.location.assign('/login')
      return Promise.reject(refreshError)
    }
  },
)
