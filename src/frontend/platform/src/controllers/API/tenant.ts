import axios from "@/controllers/request"
import {
  Tenant,
  TenantCreateForm,
  TenantDetail,
  TenantQuota,
  TenantUpdateForm,
  UserTenantItem,
} from "@/types/api/tenant"

// ── Admin CRUD ──────────────────────────────────────────

export async function createTenantApi(data: TenantCreateForm): Promise<any> {
  return await axios.post(`/api/v1/tenants/`, data)
}

export async function getTenantsApi(params: {
  keyword?: string
  status?: string
  page: number
  page_size: number
}): Promise<{ data: Tenant[]; total: number }> {
  return await axios.get(`/api/v1/tenants/`, { params })
}

export async function getTenantApi(tenantId: number): Promise<TenantDetail> {
  return await axios.get(`/api/v1/tenants/${tenantId}`)
}

export async function updateTenantApi(
  tenantId: number,
  data: TenantUpdateForm
): Promise<any> {
  return await axios.put(`/api/v1/tenants/${tenantId}`, data)
}

export async function updateTenantStatusApi(
  tenantId: number,
  status: string
): Promise<any> {
  return await axios.put(`/api/v1/tenants/${tenantId}/status`, { status })
}

export async function deleteTenantApi(tenantId: number): Promise<any> {
  return await axios.delete(`/api/v1/tenants/${tenantId}`)
}

// ── Quota ────────────────────────────────────────────────

export async function getTenantQuotaApi(
  tenantId: number
): Promise<TenantQuota> {
  return await axios.get(`/api/v1/tenants/${tenantId}/quota`)
}

export async function setTenantQuotaApi(
  tenantId: number,
  quota_config: Record<string, any>
): Promise<any> {
  return await axios.put(`/api/v1/tenants/${tenantId}/quota`, { quota_config })
}

// ── Tenant Admins ────────────────────────────────────────

export async function listTenantAdminsApi(
  tenantId: number
): Promise<{ user_ids: number[] }> {
  return await axios.get(`/api/v1/tenants/${tenantId}/admins`)
}

export async function grantTenantAdminApi(
  tenantId: number,
  userId: number
): Promise<any> {
  return await axios.post(`/api/v1/tenants/${tenantId}/admins`, {
    user_id: userId,
  })
}

export async function revokeTenantAdminApi(
  tenantId: number,
  userId: number
): Promise<any> {
  return await axios.delete(`/api/v1/tenants/${tenantId}/admins/${userId}`)
}

// ── Tenant Users ─────────────────────────────────────────

export async function getTenantUsersApi(
  tenantId: number,
  params: { page: number; page_size: number; keyword?: string }
): Promise<{ data: any[]; total: number }> {
  return await axios.get(`/api/v1/tenants/${tenantId}/users`, { params })
}

export async function addTenantUsersApi(
  tenantId: number,
  data: { user_ids: number[]; is_admin?: boolean }
): Promise<any> {
  return await axios.post(`/api/v1/tenants/${tenantId}/users`, data)
}

export async function removeTenantUserApi(
  tenantId: number,
  userId: number
): Promise<any> {
  return await axios.delete(`/api/v1/tenants/${tenantId}/users/${userId}`)
}

// ── User-facing ──────────────────────────────────────────

export async function getUserTenantsApi(): Promise<UserTenantItem[]> {
  return await axios.get(`/api/v1/user/tenants`)
}

export async function switchTenantApi(
  tenantId: number
): Promise<{ access_token: string }> {
  return await axios.post(`/api/v1/user/switch-tenant`, {
    tenant_id: tenantId,
  })
}
