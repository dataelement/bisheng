import axios from "@/controllers/request"

export interface DeveloperTokenGlobalConfig {
  ip_whitelist: string
  rate_limit_per_minute: number | null
}

export type DeveloperTokenRouteMatchType = "METHOD_PATH" | "PATH" | "PREFIX"

export interface DeveloperTokenRouteRule {
  match_type: DeveloperTokenRouteMatchType
  method?: string | null
  path: string
}

export type DeveloperTokenFileSyncMode = "fixed" | "dynamic"

export type DeveloperTokenFileSyncDynamicSource =
  | "department_id"
  | "responsible_person_id"

export interface DeveloperTokenFileSyncRule {
  category: {
    code: string
    subcategory_code: string
  }
  business_domain: {
    mode: DeveloperTokenFileSyncMode
    code: string | null
  }
  target_space: {
    mode: DeveloperTokenFileSyncMode
    knowledge_id: number | null
  }
  dynamic_source: DeveloperTokenFileSyncDynamicSource | null
}

export interface DeveloperTokenFileSyncCategoryOption {
  code: string
  label: string
  children: Array<{ code: string; label: string }>
}

export interface DeveloperTokenFileSyncBusinessDomainOption {
  code: string
  name: string
}

export interface DeveloperTokenFileSyncKnowledgeSpaceOption {
  id: number
  name: string
}

export interface DeveloperTokenPageData<T> {
  data: T[]
  total: number
}

export interface DeveloperTokenFileSyncOptions {
  tenant_id: number
  categories: DeveloperTokenFileSyncCategoryOption[]
  business_domains: DeveloperTokenFileSyncBusinessDomainOption[]
  knowledge_spaces: DeveloperTokenPageData<DeveloperTokenFileSyncKnowledgeSpaceOption>
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
  route_rule_count: number
  file_sync_rule?: DeveloperTokenFileSyncRule | null
  last_used_time?: string | null
  last_used_ip?: string | null
  created_by?: number | null
  updated_by?: number | null
  create_time?: string | null
  update_time?: string | null
}

export interface DeveloperTokenDetail extends DeveloperTokenRecord {
  ip_whitelist?: string | null
  route_whitelist?: DeveloperTokenRouteRule[] | null
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
  route_whitelist?: DeveloperTokenRouteRule[] | null
  file_sync_rule?: DeveloperTokenFileSyncRule | null
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

export async function getDeveloperTokenFileSyncOptionsApi(params: {
  tenant_id: number
  space_page?: number
  space_limit?: number
  space_keyword?: string
}): Promise<DeveloperTokenFileSyncOptions> {
  return await axios.get("/api/v1/admin/developer-tokens/config/file-sync-options", {
    params: { space_page: 1, space_limit: 50, ...params },
  })
}
