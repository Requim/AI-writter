import { apiClient } from './client'
import type { AdminTenant, AdminUser, AuthSession, QuotaUsage, TenantMember, TenantRole, TenantSummary } from '@/types/auth'

async function data<T>(request: Promise<{ data: T }>): Promise<T> {
  return (await request).data
}

export const authApi = {
  register: (payload: { email: string; password: string; tenant_name: string }) =>
    data<AuthSession>(apiClient.post('/v1/auth/register', payload)),
  login: (payload: { email: string; password: string }) =>
    data<AuthSession>(apiClient.post('/v1/auth/login', payload)),
  me: () => data<Pick<AuthSession, 'user' | 'tenants'>>(apiClient.get('/v1/auth/me')),
  logout: (refreshToken: string) => apiClient.post('/v1/auth/logout', { refresh_token: refreshToken }),
  changePassword: (payload: { current_password: string; new_password: string }) =>
    apiClient.post('/v1/auth/change-password', payload),
}

export const tenantApi = {
  list: () => data<TenantSummary[]>(apiClient.get('/v1/tenants')),
  usage: () => data<QuotaUsage>(apiClient.get('/v1/tenants/current/usage')),
  members: () => data<TenantMember[]>(apiClient.get('/v1/tenants/current/members')),
  update: (name: string) => data<{ id: string; name: string }>(apiClient.patch('/v1/tenants/current', { name })),
  invite: (role: Exclude<TenantRole, 'owner'>) => data<{ token: string; invite_path: string; expires_at: string }>(
    apiClient.post('/v1/tenants/current/invitations', { role }),
  ),
  accept: (token: string) => data<{ tenant_id: string; status: string }>(
    apiClient.post(`/v1/tenants/invitations/${encodeURIComponent(token)}/accept`),
  ),
  updateRole: (userId: string, role: Exclude<TenantRole, 'owner'>) =>
    apiClient.patch(`/v1/tenants/current/members/${userId}`, { role }),
  transferOwnership: (userId: string) => apiClient.post(`/v1/tenants/current/ownership/${userId}`),
  removeMember: (userId: string) => apiClient.delete(`/v1/tenants/current/members/${userId}`),
  leave: () => apiClient.delete('/v1/tenants/current/membership'),
}

export const adminApi = {
  tenants: () => data<AdminTenant[]>(apiClient.get('/v1/admin/tenants')),
  users: () => data<AdminUser[]>(apiClient.get('/v1/admin/users')),
  updateTenant: (tenantId: string, payload: Partial<Pick<AdminTenant, 'status' | 'ai_enabled' | 'monthly_generation_limit'>>) =>
    apiClient.patch(`/v1/admin/tenants/${tenantId}`, payload),
  updateUser: (userId: string, status: 'active' | 'suspended') =>
    apiClient.patch(`/v1/admin/users/${userId}`, { status }),
}
