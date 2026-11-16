// F019-admin-tenant-scope — axios wrappers for the admin management-view
// switch. Only global super admins may invoke these endpoints; Child
// Admins and ordinary users receive HTTP 403 + body.status_code 19701.
//
// This file intentionally carries NO UI (per spec §9 Out of Scope):
// F020 owns the `<AdminScopeSelector>` component and the
// `useAdminScope` hook that wraps these calls. Keep this surface thin so
// F020 can evolve the UI without touching the backend contract.

import axios, { bootstrapManagementRequestScope } from "@/controllers/request"
import { announceManagementScope, pauseManagementScope } from "@/controllers/managementScope"

export interface AdminScopeResponse {
  // A server response always names one concrete tenant; null is loading-only.
  scope_tenant_id: number | null
  // ISO-8601 UTC string indicating when the Redis key will naturally
  // expire if not refreshed. `null` when no scope is set.
  expires_at: string | null
}

/**
 * Select a concrete tenant for the caller's
 * management-view scope. The server writes an `admin.scope_switch` audit
 * row and returns the new state.
 *
 * @throws Response body `status_code` === 19701 when caller is not a
 *   global super admin (HTTP 403). The global axios response interceptor
 *   handles 403 routing.
 * @throws Response body `status_code` === 19702 when `tenantId` does not
 *   match any tenant row (HTTP 400).
 */
export async function setTenantScope(
  tenantId: number,
): Promise<AdminScopeResponse> {
  pauseManagementScope();
  try {
    await axios.post("/api/v1/admin/tenant-scope", { tenant_id: tenantId });
    const confirmed: AdminScopeResponse = await axios.get("/api/v1/admin/request-scope");
    if (confirmed.scope_tenant_id) announceManagementScope(confirmed.scope_tenant_id);
    return confirmed;
  } catch (error) {
    // Redis may already have changed even when audit or response delivery failed.
    try {
      const confirmed: AdminScopeResponse = await axios.get("/api/v1/admin/request-scope");
      if (confirmed.scope_tenant_id) announceManagementScope(confirmed.scope_tenant_id);
    } catch { /* Keep requests paused until an explicit successful confirmation. */ }
    throw error;
  }
}

/**
 * Read the caller's current management-view scope. Returns
 * `{scope_tenant_id: null, expires_at: null}` if no scope is active.
 */
export async function getTenantScope(): Promise<AdminScopeResponse> {
  const proof = await bootstrapManagementRequestScope();
  return { ...proof, expires_at: null }
}
