import axios from "@/controllers/request"

export interface DeveloperTokenGlobalConfig {
  ip_whitelist: string
  rate_limit_per_minute: number | null
}

export interface DeveloperTokenRecord {
  id: number
  tenant_id: number
  tenant_name?: string | null
  user_id: number
  user_name?: string | null
  name: string
  token_prefix: string
  enabled: boolean
  override_ip_whitelist: boolean
  override_rate_limit: boolean
  rate_limit_per_minute?: number | null
  last_used_time?: string | null
  last_used_ip?: string | null
  created_by?: number | null
  updated_by?: number | null
  create_time?: string | null
  update_time?: string | null
}

export interface DeveloperTokenDetail extends DeveloperTokenRecord {
  ip_whitelist?: string | null
}

export interface DeveloperTokenPage {
  data: DeveloperTokenRecord[]
  total: number
}

export interface DeveloperTokenPayload {
  name: string
  user_id?: number
  department_id?: number
  dept_id?: string
  enabled: boolean
  override_ip_whitelist: boolean
  ip_whitelist?: string
  override_rate_limit: boolean
  rate_limit_per_minute?: number | null
}

export interface DeveloperTokenCreateResponse {
  token: DeveloperTokenRecord
  plaintext_token: string
}

export interface DeveloperTokenSecretResponse {
  id: number
  token_prefix: string
  plaintext_token: string
}

export async function listDeveloperTokensApi(params: {
  page?: number
  limit?: number
  keyword?: string
  tenant_id?: number
  user_id?: number
  enabled?: boolean
} = {}): Promise<DeveloperTokenPage> {
  return await axios.get("/api/v1/admin/developer-tokens", {
    params: { page: 1, limit: 20, ...params },
  })
}

export async function createDeveloperTokenApi(
  data: DeveloperTokenPayload
): Promise<DeveloperTokenCreateResponse> {
  return await axios.post("/api/v1/admin/developer-tokens", data)
}

export async function getDeveloperTokenDetailApi(
  tokenId: number
): Promise<DeveloperTokenDetail> {
  return await axios.get(`/api/v1/admin/developer-tokens/${tokenId}`)
}

export async function updateDeveloperTokenApi(
  tokenId: number,
  data: Partial<DeveloperTokenPayload>
): Promise<DeveloperTokenRecord> {
  return await axios.put(`/api/v1/admin/developer-tokens/${tokenId}`, data)
}

export async function deleteDeveloperTokenApi(tokenId: number): Promise<void> {
  return await axios.delete(`/api/v1/admin/developer-tokens/${tokenId}`)
}

export async function viewDeveloperTokenSecretApi(
  tokenId: number
): Promise<DeveloperTokenSecretResponse> {
  return await axios.get(`/api/v1/admin/developer-tokens/${tokenId}/secret`)
}

export async function getDeveloperTokenGlobalConfigApi(): Promise<DeveloperTokenGlobalConfig> {
  return await axios.get("/api/v1/admin/developer-tokens/config/global")
}

export async function updateDeveloperTokenGlobalConfigApi(
  data: DeveloperTokenGlobalConfig
): Promise<DeveloperTokenGlobalConfig> {
  return await axios.put("/api/v1/admin/developer-tokens/config/global", data)
}
