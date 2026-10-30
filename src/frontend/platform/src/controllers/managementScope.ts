/** Request snapshots are learned from server responses, never restored as authority from storage. */
const STORAGE_KEY = 'bs:management-scope'
let effectiveTenant: number | null = null

export function managementRequestScope() { return effectiveTenant }

export function acceptManagementScope(value: unknown) {
  if (value === null) { effectiveTenant = null; return }
  const parsed = typeof value === 'number' ? value : Number(value)
  if (Number.isSafeInteger(parsed) && parsed > 0) effectiveTenant = parsed
}

export function announceManagementScope(tenantId: number) {
  acceptManagementScope(tenantId)
  window.dispatchEvent(new Event('bisheng:management-scope-changed'))
  try { window.localStorage.setItem(STORAGE_KEY, `${tenantId}:${Date.now()}`) } catch { /* Cross-tab sync is optional; current-tab scope is already invalidated. */ }
}

export function requiresManagementScope(method: string, raw: string): boolean {
  const url = new URL(raw, window.location.origin)
  if (url.searchParams.get('purpose') === 'approval') return false
  const path = url.pathname.replace(/\/$/, '')
  const verb = method.toUpperCase()
  const rules: [readonly string[], RegExp][] = [
    [['PATCH','DELETE'], /^\/api\/v1\/apps\/[^/]+$/],
    [['POST'], /^\/api\/v1\/apps\/[^/]+\/actions\/[^/]+$/],
    [['POST','PUT','DELETE'], /^\/api\/v1\/apps\/[^/]+\/secrets\/[^/]+$/],
    [['PATCH'], /^\/api\/v1\/apps\/[^/]+\/data\/tables\/[^/]+\/rows(?:\/[^/]+)?$/],
    [['POST','PATCH'], /^\/api\/v1\/apps\/[^/]+\/runtime\/(?:materials(?:\/[^/]+)?|restore|operations\/[^/]+\/cancel)$/],
    [['POST'], /^\/api\/v1\/apps\/[^/]+\/(?:withdraw|publish\/manual-publish)$/],
    [['POST','DELETE'], /^\/api\/v1\/apps\/[^/]+\/versions\/[^/]+\/preview(?:\/[^/]+)?$/],
    [['POST','PUT','PATCH','DELETE'], /^\/api\/v1\/(?:roles|user-groups)(?:\/[^/]+)?$/],
    [['POST'], /^\/api\/v1\/workflow\/(?:create|versions|change_version)$/],
    [['PATCH'], /^\/api\/v1\/workflow\/(?:update\/[^/]+|status)$/],
    [['PUT','DELETE'], /^\/api\/v1\/workflow\/versions\/[^/]+$/],
    [['DELETE'], /^\/api\/v1\/flows\/[^/]+$/],
    [['POST','PUT'], /^\/api\/v1\/assistant$/],
    [['POST'], /^\/api\/v1\/assistant\/(?:delete|status|flow|tool)$/],
    [['POST'], /^\/api\/v1\/knowledge\/(?:create|copy|qa\/copy|upload(?:\/[^/]+)?|tags|file\/tags(?:\/batch)?)$/],
  ]
  return rules.some(([methods, pattern]) => methods.includes(verb) && pattern.test(path))
}

export function guardManagementResponse(headers: Record<string, unknown>, snapshot: number | null | undefined) {
  const raw = headers?.['x-management-tenant']
  if (raw === undefined) return
  const tenantId = Number(raw)
  if (!Number.isSafeInteger(tenantId) || tenantId <= 0) return
  if (snapshot != null && effectiveTenant != null && snapshot !== effectiveTenant) throw new Error('management_scope_stale')
  if (effectiveTenant !== null && tenantId !== effectiveTenant) {
    announceManagementScope(tenantId)
    throw new Error('management_scope_changed')
  }
  acceptManagementScope(tenantId)
}
