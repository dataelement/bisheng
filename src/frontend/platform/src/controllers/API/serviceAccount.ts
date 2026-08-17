/**
 * F049 service-account management API (`/api/v1/service-accounts/**`).
 *
 * All calls go through the wrapped request module (constitution C7) — the
 * interceptor unwraps the platform envelope, so every function resolves with
 * the payload itself. Rejections carry the decoded `status_message`; envelope
 * `403` is already handled globally, so callers never branch on it.
 *
 * Paths carry **no trailing slash** — the backend router registers
 * `""` / `"/{id}"` and a trailing slash would 307 (dropping the method on some
 * proxies). `GET /scopes` is registered before `GET /{id}` on the backend, so
 * it is a real route and not an id lookup.
 *
 * Resource-grant calls (`/{id}/grants*`) are appended to this file by T066.
 */
import axios from "@/controllers/request"
import {
  ApiKeyItem,
  KeyIssueForm,
  KeyIssuedResponse,
  KeyUpdateForm,
  OpenApiScopeCatalog,
  ServiceAccountCreateForm,
  ServiceAccountDeleteResult,
  ServiceAccountDetail,
  ServiceAccountPage,
  ServiceAccountUpdateForm,
} from "@/types/api/serviceAccount"

const BASE = "/api/v1/service-accounts"

/**
 * One page of the current admin scope's service accounts. In multi-tenant
 * deployments the tenant comes from the F019 ScopeBar (this prefix is in
 * `MANAGEMENT_API_PREFIXES`), so callers must refetch when the scope changes.
 */
export async function getServiceAccountsApi(params: {
  page: number
  pageSize: number
  keyword?: string
}): Promise<ServiceAccountPage> {
  return await axios.get(BASE, {
    params: {
      page: params.page,
      page_size: params.pageSize,
      keyword: params.keyword || undefined,
    },
  })
}

export async function createServiceAccountApi(
  data: ServiceAccountCreateForm
): Promise<ServiceAccountDetail> {
  return await axios.post(BASE, data)
}

export async function getServiceAccountApi(id: number): Promise<ServiceAccountDetail> {
  return await axios.get(`${BASE}/${id}`)
}

/** Absent fields stay unchanged (name / description / resource owner). */
export async function updateServiceAccountApi(
  id: number,
  data: ServiceAccountUpdateForm
): Promise<ServiceAccountDetail> {
  return await axios.patch(`${BASE}/${id}`, data)
}

export async function enableServiceAccountApi(id: number): Promise<ServiceAccountDetail> {
  return await axios.post(`${BASE}/${id}/enable`)
}

/** Keys stop working within 5s; grants and configuration are kept (AC-47). */
export async function disableServiceAccountApi(id: number): Promise<ServiceAccountDetail> {
  return await axios.post(`${BASE}/${id}/disable`)
}

/** Never blocked — the returned `grants` is what the deletion took down (AC-48). */
export async function deleteServiceAccountApi(id: number): Promise<ServiceAccountDeleteResult> {
  return await axios.delete(`${BASE}/${id}`)
}

export async function getServiceAccountKeysApi(id: number): Promise<ApiKeyItem[]> {
  return await axios.get(`${BASE}/${id}/keys`)
}

/** The only response that ever carries a plaintext key (AC-02). */
export async function issueKeyApi(id: number, data: KeyIssueForm): Promise<KeyIssuedResponse> {
  return await axios.post(`${BASE}/${id}/keys`, data)
}

/**
 * Same key, new configuration — effective on the next call (AC-08).
 * Absent = unchanged; `expires_at: null` clears the expiry; `scopes: []`
 * clears every bit.
 */
export async function updateKeyApi(
  id: number,
  keyId: number,
  data: KeyUpdateForm
): Promise<ApiKeyItem> {
  return await axios.patch(`${BASE}/${id}/keys/${keyId}`, data)
}

export async function revokeKeyApi(id: number, keyId: number): Promise<ApiKeyItem> {
  return await axios.post(`${BASE}/${id}/keys/${keyId}/revoke`)
}

export async function revokeAllKeysApi(id: number): Promise<{ revoked: number }> {
  return await axios.post(`${BASE}/${id}/keys/revoke-all`)
}

/**
 * Permission bits this deployment offers. The three `local_dev_toolkit` bits
 * are present only where the open capability layer is deployed — the same
 * predicate the backend uses to reject them at issue time, so the form can
 * never offer a bit the service would refuse (AC-13 / AC-49).
 */
export async function getOpenApiScopesApi(): Promise<OpenApiScopeCatalog> {
  return await axios.get(`${BASE}/scopes`)
}
