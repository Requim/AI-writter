import type { PropsWithChildren } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'

export function ProtectedRoute({ children }: PropsWithChildren) {
  const location = useLocation()
  const accessToken = useAuthStore((state) => state.accessToken)
  const currentTenantId = useAuthStore((state) => state.currentTenantId)
  if (!accessToken) {
    return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />
  }
  if (!currentTenantId) return <Navigate to="/login" replace />
  return children
}

export function PlatformAdminRoute({ children }: PropsWithChildren) {
  const user = useAuthStore((state) => state.user)
  if (!user?.is_platform_admin) return <Navigate to="/" replace />
  return children
}
