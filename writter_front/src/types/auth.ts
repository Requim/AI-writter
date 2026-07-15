export type TenantRole = 'owner' | 'admin' | 'member'

export interface AuthUser {
  id: string
  email: string
  is_platform_admin: boolean
  status: string
}

export interface TenantSummary {
  id: string
  name: string
  slug: string
  role: TenantRole
  status: string
  ai_enabled: boolean
  monthly_generation_limit: number
}

export interface AuthSession {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
  user: AuthUser
  tenants: TenantSummary[]
}

export interface TenantMember {
  user_id: string
  email: string
  role: TenantRole
  status: string
  joined_at: string
}

export interface QuotaUsage {
  used: number
  limit: number
  remaining: number
  ai_enabled: boolean
  period_start: string
}

export interface AdminTenant {
  id: string
  name: string
  slug: string
  status: 'active' | 'suspended'
  ai_enabled: boolean
  monthly_generation_limit: number
  member_count: number
  usage: number
}

export interface AdminUser {
  id: string
  email: string
  status: 'active' | 'suspended'
  is_platform_admin: boolean
  tenant_count: number
  created_at: string
}
