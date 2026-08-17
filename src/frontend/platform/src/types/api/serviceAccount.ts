/**
 * F049 open-API auth baseline — service-account management types.
 *
 * Mirrors the backend DTOs in `bisheng/open_api/domain/schemas/`. Two contract
 * facts drive the shapes here:
 *
 * 1. Management responses ride the platform envelope (HTTP 200 +
 *    `{status_code, status_message, data}`); `@/controllers/request` unwraps
 *    `data`, so every type below is the *unwrapped* payload.
 * 2. A key row carries no `status` column — validity is derived from
 *    `is_valid` / `revoked_at` / `expires_at` (backend K3).
 */

export type ServiceAccountStatus = "enabled" | "disabled" | "deleted"

/** Resource owner (AC-23). `disabled` drives the AC-28 / AC-42 list highlight. */
export interface ServiceAccountOwner {
  user_id: number
  user_name: string | null
  disabled: boolean
}

/** One row of the service-account list (AC-42 columns). */
export interface ServiceAccountItem {
  /** = user.user_id of the service-account principal */
  id: number
  name: string
  description: string | null
  status: ServiceAccountStatus
  disabled_at: string | null
  deleted_at: string | null
  active_key_count: number
  resource_owner: ServiceAccountOwner | null
  owner_disabled: boolean
  /** max(last_used_at) over the account's keys; null = never called */
  last_used_at: string | null
  /** No call within `idle_days` — the list nudges the admin to disable it */
  idle: boolean
  created_by: number | null
  creator_name: string | null
  create_time: string | null
  update_time: string | null
}

export interface ServiceAccountDetail extends ServiceAccountItem {
  tenant_id: number
}

/**
 * List envelope. `idle_days` is deployment configuration
 * (`open_api.service_account_idle_days`, default 90) — never hardcode it.
 */
export interface ServiceAccountPage {
  data: ServiceAccountItem[]
  total: number
  idle_days: number
}

/** `DELETE /{id}` pre-flight result: the grants the deletion takes down (AC-48). */
export interface ServiceAccountDeleteResult {
  id: number
  /** Structurally empty until the subject-side reverse lookup ships (T065) */
  grants: unknown[]
}

/** Masked key row. There is no `status` field — see `deriveKeyState`. */
export interface ApiKeyItem {
  id: number
  name: string
  /** `bs-sak-********` + last four characters (AC-02) */
  key_mask: string
  scopes: string[]
  expires_at: string | null
  revoked_at: string | null
  revoke_reason: string | null
  last_used_at: string | null
  /** revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now) */
  is_valid: boolean
  created_by: number | null
  creator_name: string | null
  create_time: string | null
  update_time: string | null
}

/** Issue response — the single place a plaintext key ever appears (AC-02). */
export interface KeyIssuedResponse extends ApiKeyItem {
  plaintext: string
}

/** One `(method, path)` pair a scope unlocks; `WS` marks a WebSocket route. */
export interface OpenApiScopeEndpoint {
  method: string
  path: string
}

/**
 * One grantable permission bit. The backend ships **i18n keys only** — every
 * `*_key` field is resolved against the platform `serviceAccount` namespace.
 */
export interface OpenApiScope {
  code: string
  /** `workflow` | `assistant` | `knowledge` | `local_dev_toolkit` */
  group: string
  label_key: string
  desc_key: string
  endpoints: OpenApiScopeEndpoint[]
  requires_open_platform: boolean
  /** Set when the bit is issuable but its endpoints ship later (`chat:invoke`) */
  pending_note_key: string | null
  /** Extra warnings the issue form renders prominently (AC-13) */
  hint_keys: string[]
}

export interface OpenApiScopeCatalog {
  scopes: OpenApiScope[]
  open_platform_enabled: boolean
}

export interface ServiceAccountCreateForm {
  name: string
  description?: string | null
  resource_owner_user_id: number
}

/**
 * PATCH semantics: an absent field stays unchanged. Never send a `null`
 * placeholder for a field you do not mean to change.
 */
export interface ServiceAccountUpdateForm {
  name?: string
  description?: string | null
  resource_owner_user_id?: number
}

export interface KeyIssueForm {
  name: string
  scopes: string[]
  /** ISO-8601; omitted / null = never expires */
  expires_at?: string | null
}

/**
 * PATCH semantics: absent = unchanged; `expires_at: null` *explicitly clears*
 * the expiry; `scopes: []` clears every permission bit.
 */
export interface KeyUpdateForm {
  name?: string
  scopes?: string[]
  expires_at?: string | null
}
