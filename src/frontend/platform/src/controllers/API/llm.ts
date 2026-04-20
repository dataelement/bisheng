// Axios wrappers for LLM server CRUD under the Tenant-tree model.
// Global super admins and Child Admins may call POST/PUT/DELETE; the
// backend's get_tenant_admin_user dependency gates access.

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
  // True when the caller sees this server via Root → Child share.
  // Drives the readonly Badge + disabled edit buttons on the UI.
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
  // Root-only switch; true fans out to all Children via FGA shared_with
  // tuples. Ignored by the backend when the target tenant is not Root.
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

export async function listLLMServers(): Promise<LLMServerInfo[]> {
  return await axios.get("/api/v1/llm")
}

/** Root-owned servers currently shared to ≥1 Child (mount-preview dialog).
 *  Super-admin only; non-super callers receive HTTP 403. */
export async function listSharedLLMServersForMountPreview(): Promise<LLMServerInfo[]> {
  return await axios.get("/api/v1/llm", { params: { only_shared: true } })
}

export async function getLLMServerDetail(serverId: number): Promise<LLMServerInfo> {
  return await axios.get("/api/v1/llm/info", { params: { server_id: serverId } })
}

export async function createLLMServer(req: LLMServerUpsertReq): Promise<LLMServerInfo> {
  return await axios.post("/api/v1/llm", req)
}

export async function updateLLMServer(req: LLMServerUpsertReq): Promise<LLMServerInfo> {
  return await axios.put("/api/v1/llm", req)
}

export async function deleteLLMServer(serverId: number): Promise<void> {
  return await axios.delete("/api/v1/llm", { data: { server_id: serverId } })
}

export async function setModelOnline(modelId: number, online: boolean): Promise<LLMModelInfo> {
  return await axios.post("/api/v1/llm/online", { model_id: modelId, online })
}
