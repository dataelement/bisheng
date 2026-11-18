import { BrowserScopeSession, needsBrowserScope, isScopeReconfirmationChange } from "@bisheng/api-client";
const session = new BrowserScopeSession();
/** Request snapshots are learned from server responses, never restored as authority from storage. */
const STORAGE_KEY = "bs:management-scope";


export function managementRequestScope() {
  return session.tenant;
}

export function acceptManagementScope(value: unknown) {
  if (value === null) {
    session.reset();
    return;
  }
  const parsed = typeof value === "number" ? value : Number(value);
  if (Number.isSafeInteger(parsed) && parsed > 0) session.accept({scope_tenant_id: parsed});
}

export function announceManagementScope(tenantId: number) {
  acceptManagementScope(tenantId);
  window.dispatchEvent(new Event("bisheng:management-scope-changed"));
  try {
    window.localStorage.setItem(STORAGE_KEY, `${tenantId}:${Date.now()}`);
  } catch {
    /* Cross-tab sync is optional; current-tab scope is already invalidated. */
  }
}

export function requiresManagementScope(method: string, raw: string, baseURL?: string): boolean {
  return needsBrowserScope(method, raw, window.location.origin, baseURL);
}

export function pauseManagementScope() {
  session.pause();
}

export function beginManagementScopeSwitch() {
  return session.beginSwitch();
}

export async function readManagementScope(
  bootstrap: () => Promise<{scope_tenant_id: number; source?: string}>,
  confirm: () => Promise<{scope_tenant_id: number; source?: string}>,
) {
  if (!session.isPaused) return session.ensure(bootstrap);
  try {
    return await session.reconfirm(confirm);
  } catch (error) {
    if (isScopeReconfirmationChange(error)) window.dispatchEvent(new Event("bisheng:management-scope-changed"));
    throw error;
  }
}

export function pauseManagementScopeForRequest(config?: {url?: string; method?: string; managementScopeSnapshot?: number | null}) {
  if (config?.managementScopeSnapshot != null && config.managementScopeSnapshot === session.tenant) session.pause();
}

export function guardManagementResponse(
  headers: Record<string, unknown>,
  snapshot: number | null | undefined,
) {
  if (snapshot != null && snapshot !== session.tenant) throw new Error("management_scope_stale");
  const raw = headers?.["x-management-tenant"];
  if (raw === undefined) return;
  const tenantId = Number(raw);
  if (!Number.isSafeInteger(tenantId) || tenantId <= 0) return;
  if (
    snapshot != null &&
    session.tenant != null &&
    snapshot !== session.tenant
  )
    throw new Error("management_scope_stale");
  if (session.tenant !== null && tenantId !== session.tenant) {
    announceManagementScope(tenantId);
    throw new Error("management_scope_changed");
  }
  if (session.tenant === null) throw new Error("management_scope_unavailable");
}
