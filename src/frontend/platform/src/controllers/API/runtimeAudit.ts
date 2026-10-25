import request from '@/controllers/request'

export type RuntimeAuditKind = 'model' | 'capability' | 'access'
export type RuntimeAuditFilters = {
  time_range: 'recent7d' | 'custom' | 'all'
  start_time?: string
  end_time?: string
  app_id?: string
  visitor_id?: number
  credential_id?: number
  tenant_id?: number
}
export type RuntimeAuditRow = Record<string, string | number | boolean | null>
export interface RuntimeAuditPage {
  items: RuntimeAuditRow[]
  next_cursor: string | null
  snapshot_id: string
  matched_count: number | null
}
export interface RuntimeAuditCandidate {
  id: string
  label: string
  deleted_or_revoked: boolean | null
}
export interface RuntimeAuditExport {
  export_id: string
  status: 'pending' | 'running' | 'ready' | 'failed' | 'expired'
  processed_rows?: number
  final_count?: number | null
  selection_started_at?: string | null
  safe_reason?: string | null
}
const base = '/api/v1/app-runtime-audit'
export async function getRuntimeAuditRecords(kind: RuntimeAuditKind, filters: RuntimeAuditFilters, cursor?: string): Promise<RuntimeAuditPage> {
  return await request.get(`${base}/records/${kind}`, { params: { ...filters, cursor, limit: 50 } })
}
export async function getRuntimeAuditCandidates(kind: RuntimeAuditKind, dimension: 'app' | 'visitor' | 'credential', filters: RuntimeAuditFilters, query = '', offset = 0): Promise<{ items: RuntimeAuditCandidate[]; has_more: boolean }> {
  return await request.get(`${base}/candidates/${dimension}`, { params: { ...filters, kind, query, offset, limit: 100 } })
}
export async function createRuntimeAuditExport(snapshotId: string, tenantId?: number): Promise<RuntimeAuditExport> {
  return await request.post(`${base}/exports`, { snapshot_id: snapshotId, request_id: crypto.randomUUID(), tenant_id: tenantId })
}
export async function getRuntimeAuditExport(id: string, tenantId?: number): Promise<RuntimeAuditExport> {
  return await request.get(`${base}/exports/${encodeURIComponent(id)}`, { params: { tenant_id: tenantId } })
}
export async function cancelRuntimeAuditExport(id: string, tenantId?: number): Promise<RuntimeAuditExport> {
  return await request.post(`${base}/exports/${encodeURIComponent(id)}/cancel`, {}, { params: { tenant_id: tenantId } })
}
export async function downloadRuntimeAuditExport(id: string, tenantId?: number): Promise<Blob> {
  return await request.get(`${base}/exports/${encodeURIComponent(id)}/download`, { responseType: 'blob', params: { tenant_id: tenantId } })
}
