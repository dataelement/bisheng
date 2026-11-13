import { BrowserScopeSession, needsBrowserScope } from "@bisheng/api-client";
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

export function requiresManagementScope(method: string, raw: string): boolean {
  return needsBrowserScope(method, raw, window.location.origin);
}

export function pauseManagementScope() {
  session.pause();
}

export function ensureManagementScope(loader: () => Promise<{scope_tenant_id: number; source?: string}>) {
  return session.ensure(loader);
}

export function guardManagementResponse(
  headers: Record<string, unknown>,
  snapshot: number | null | undefined,
) {
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
