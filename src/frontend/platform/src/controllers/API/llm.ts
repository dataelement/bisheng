// F020-llm-tenant-isolation — axios wrappers for LLM server CRUD under
// the Tenant-tree model. Global super admins and Child Admins may call
// POST/PUT/DELETE (the backend's get_tenant_admin_user dependency gates
// access; non-admins receive HTTP 403 + body.status_code 19801).
//
// Only the LLM-specific fields live here. Generic admin-scope helpers
// live in admin.ts (F019 owned); the `useAdminScope` hook (F020 T13)
// wraps admin.ts for the model-page scope selector.

import axios from "@/controllers/request"

export interface LLMModelInfo {
  id: number
  server_id: number
  name: string
  description?: string
  model_name: string
  model_type: string
  online: boolean
  status: number
  remark?: string
  tenant_id: number
  config?: Record<string, unknown>
}

export interface LLMServerInfo {
  id: number
  name: string
  description?: string
  type: string
  limit_flag: boolean
  limit: number
  tenant_id: number
  user_id: number
  config?: Record<string, unknown>
  models: LLMModelInfo[]
  // F020: true when the caller sees this server via Root → Child share
  // (either a Child Admin seeing a Root-shared row, or a super admin
  // under an F019 Child scope). The UI uses this to render the
  // "Root 共享（只读）" Badge and disable edit buttons.
  is_root_shared_readonly: boolean
}

export interface LLMServerUpsertReq {
  id?: number
  name: string
  description?: string
  type: string
  limit_flag?: boolean
  limit?: number
  config?: Record<string, unknown>
  // F020 AC-01/AC-02/AC-04: Root-only switch. True (default) fans the
  // new server out to every Child via F017 shared_with tuples; false
  // keeps it Root-private. Ignored by the backend when the target
  // tenant is not Root.
  share_to_children?: boolean
  models: Array<{
    id?: number
    name: string
    description?: string
    model_name: string
    model_type: string
    online?: boolean
    config?: Record<string, unknown>
  }>
}

/** GET /api/v1/llm — list servers visible to the caller (own + Root-shared). */
export async function listLLMServers(): Promise<LLMServerInfo[]> {
  return await axios.get("/api/v1/llm")
}

/**
 * GET /api/v1/llm?only_shared=true — mount-child dialog preview (AC-17).
 * Returns Root-owned servers currently shared to at least one Child.
 * Super-admin only; non-super callers receive HTTP 403 + 19803.
 */
export async function listSharedLLMServersForMountPreview(): Promise<LLMServerInfo[]> {
  return await axios.get("/api/v1/llm", { params: { only_shared: true } })
}

/** GET /api/v1/llm/info — server detail (config unmasked for super/owner). */
export async function getLLMServerDetail(serverId: number): Promise<LLMServerInfo> {
  return await axios.get("/api/v1/llm/info", { params: { server_id: serverId } })
}

/** POST /api/v1/llm — create a server under the caller's current tenant. */
export async function createLLMServer(req: LLMServerUpsertReq): Promise<LLMServerInfo> {
  return await axios.post("/api/v1/llm", req)
}

/** PUT /api/v1/llm — update a server; routes share_to_children to
 *  aupdate_server_share when the target is Root (AC-04). */
export async function updateLLMServer(req: LLMServerUpsertReq): Promise<LLMServerInfo> {
  return await axios.put("/api/v1/llm", req)
}

/** DELETE /api/v1/llm — delete a server. DAO enforces the Root-only
 *  read-only rule (19801) and cascades FGA shared_with cleanup. */
export async function deleteLLMServer(serverId: number): Promise<void> {
  return await axios.delete("/api/v1/llm", { data: { server_id: serverId } })
}

/** POST /api/v1/llm/online — flip a model's online flag. */
export async function setModelOnline(modelId: number, online: boolean): Promise<LLMModelInfo> {
  return await axios.post("/api/v1/llm/online", { model_id: modelId, online })
}
