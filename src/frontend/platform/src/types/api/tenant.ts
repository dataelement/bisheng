export interface Tenant {
  id: number
  tenant_name: string
  tenant_code: string
  logo: string | null
  status: string
  user_count: number
  storage_used_gb: number | null
  storage_quota_gb: number | null
  create_time: string | null
}

export interface TenantDetail extends Tenant {
  root_dept_id: number | null
  contact_name: string | null
  contact_phone: string | null
  contact_email: string | null
  quota_config: Record<string, any> | null
  storage_config: Record<string, any> | null
  admin_users: TenantUser[]
}

export interface TenantQuota {
  quota_config: Record<string, any> | null
  usage: Record<string, any>
}

export interface UserTenantItem {
  tenant_id: number
  tenant_name: string
  tenant_code: string
  logo: string | null
  status: string
  last_access_time: string | null
  is_default: number
}

export interface TenantCreateForm {
  tenant_name: string
  tenant_code: string
  logo?: string
  contact_name?: string
  contact_phone?: string
  contact_email?: string
  quota_config?: Record<string, any>
  admin_user_ids: number[]
}

export interface TenantUpdateForm {
  tenant_name?: string
  logo?: string
  contact_name?: string
  contact_phone?: string
  contact_email?: string
}

export interface TenantUser {
  user_id: number
  user_name: string
  avatar: string | null
  join_time: string | null
}
