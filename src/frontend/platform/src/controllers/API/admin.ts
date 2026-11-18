// Existing management-view HTTP contract. Only global super admins may
// change the selection; authenticated users can read their confirmed scope.

import axios, { bootstrapManagementRequestScope } from "@/controllers/request"
import { announceManagementScope, beginManagementScopeSwitch } from "@/controllers/managementScope"

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
  const finishSwitch = beginManagementScopeSwitch();
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
  } finally {
    finishSwitch();
  }
}

/**
 * Read the confirmed request scope. A paused session uses a strict server GET;
 * an unavailable or expired selection rejects instead of creating a default.
 */
export async function getTenantScope(): Promise<AdminScopeResponse> {
  const proof = await bootstrapManagementRequestScope();
  return { ...proof, expires_at: null }
}
