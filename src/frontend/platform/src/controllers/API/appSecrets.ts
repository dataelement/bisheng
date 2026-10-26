import request from '@/controllers/request'

export type RebuildOperation = {
  operation_id: string
  status: string
  stage: string
  failure_reason: string | null
}
export interface AppSecretItem {
  name: string
  present: boolean
  mask?: string | null
  updated_at?: string | null
  approved_reference: boolean
  pending_reference: boolean
}
export interface AppSecrets {
  revision: number
  updated_at: string | null
  items: AppSecretItem[]
  runtime: {
    comparison: 'same' | 'different' | 'unknown' | 'not_running'
    saved_revision: number
    running_operation_id: string | null
    running_version_id: string | null
    route_epoch: number | null
    changed_names: string[]
    rebuild_operation: RebuildOperation | null
  }
}
export interface SecretChangeResult {
  revision: number
  present: boolean
  updated_at: string
}
export interface SecretRebuildRequest {
  request_id: string
  expected_version_id: string
  expected_config_revision: number
  expected_route_epoch: number
  confirm_restart: true
}
function endpoint(appId: string) {
  return `/api/v1/apps/${encodeURIComponent(appId)}/secrets`
}
export async function getAppSecrets(appId: string): Promise<AppSecrets> {
  return await request.get(endpoint(appId))
}
export async function saveAppSecret(appId: string, name: string, value: string, revision: number): Promise<SecretChangeResult> {
  return await request.put(`${endpoint(appId)}/${encodeURIComponent(name)}`, { value, expected_revision: revision })
}
export async function deleteAppSecret(appId: string, name: string, revision: number): Promise<SecretChangeResult> {
  return await request.delete(`${endpoint(appId)}/${encodeURIComponent(name)}`, { data: { expected_revision: revision, confirm_online_impact: true } })
}
export async function rebuildAppSecrets(appId: string, body: SecretRebuildRequest): Promise<{ operation_id: string; status: string }> {
  return await request.post(`${endpoint(appId)}/rebuild`, body)
}
