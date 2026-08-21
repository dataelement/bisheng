import axios from "@/controllers/request"

export type ApiRateLimitMatchType = "METHOD_PATH" | "PATH" | "PREFIX"
export type ApiRateLimitMethod =
  | "GET"
  | "POST"
  | "PUT"
  | "PATCH"
  | "DELETE"
  | "OPTIONS"
  | "HEAD"

export interface ApiRateLimitLimits {
  second: number | null
  minute: number | null
  hour: number | null
  day: number | null
}

export interface ApiRateLimitPolicy {
  limits: ApiRateLimitLimits
  message: string
}

export interface ApiRateLimitRouteRule extends ApiRateLimitPolicy {
  id: string
  match_type: ApiRateLimitMatchType
  method: ApiRateLimitMethod | null
  path: string
}

export interface ApiRateLimitConfig {
  schema_version: number
  revision: number
  global: ApiRateLimitPolicy
  routes: ApiRateLimitRouteRule[]
  updated_at: string | null
  updated_by: number | null
}

export interface ApiRateLimitConfigUpdate {
  expected_revision: number
  global: ApiRateLimitPolicy
  routes: ApiRateLimitRouteRule[]
}

export interface ApiRateLimitRouteCatalogItem {
  method: ApiRateLimitMethod
  path: string
  tags: string[]
  primary_tag: string
  name: string
  summary: string
}

export interface ApiRateLimitRouteCatalog {
  items: ApiRateLimitRouteCatalogItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
  categories: string[]
}

export interface ApiRateLimitRouteCatalogQuery {
  keyword?: string
  method?: ApiRateLimitMethod
  tag?: string
  page?: number
  page_size?: number
}

export async function getApiRateLimitConfigApi(): Promise<ApiRateLimitConfig> {
  return await axios.get("/api/v1/admin/api-rate-limit/config")
}

export async function updateApiRateLimitConfigApi(
  data: ApiRateLimitConfigUpdate
): Promise<ApiRateLimitConfig> {
  return await axios.put("/api/v1/admin/api-rate-limit/config", data)
}

export async function getApiRateLimitRoutesApi(
  query: ApiRateLimitRouteCatalogQuery = {}
): Promise<ApiRateLimitRouteCatalog> {
  return await axios.get("/api/v1/admin/api-rate-limit/routes", {
    params: query
  })
}
