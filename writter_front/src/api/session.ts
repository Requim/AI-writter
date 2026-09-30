import axios from 'axios'
import { useAuthStore } from '@/stores/authStore'
import type { AuthSession } from '@/types/auth'

let refreshPromise: Promise<AuthSession> | undefined

class MissingRefreshTokenError extends Error {}

/** 仅明确失效的凭证需要重新登录，网关和网络故障不清空会话。 */
export function isSessionInvalid(error: unknown): boolean {
  return error instanceof MissingRefreshTokenError || (axios.isAxiosError(error)
    && [401, 403].includes(error.response?.status ?? 0))
}

/** 让所有请求共享同一次令牌刷新，避免并发请求轮换刷新令牌。 */
export function refreshSession(): Promise<AuthSession> {
  const refreshToken = useAuthStore.getState().refreshToken
  if (!refreshToken) return Promise.reject(new MissingRefreshTokenError('No refresh token'))
  refreshPromise ??= axios
    .post<AuthSession>('/api/v1/auth/refresh', { refresh_token: refreshToken }, { timeout: 15_000 })
    .then(({ data }) => {
      useAuthStore.getState().setSession(data)
      return data
    })
    .finally(() => { refreshPromise = undefined })
  return refreshPromise
}

/** 清理无效会话，并将用户带回触发失效时所在页面。 */
export function redirectToLogin(): void {
  useAuthStore.getState().clear()
  if (window.location.pathname.startsWith('/login')) return
  const next = `${window.location.pathname}${window.location.search}`
  window.location.assign(`/login?next=${encodeURIComponent(next)}`)
}
