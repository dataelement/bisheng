export interface ServiceAccountOwner {
  user_id: number
  user_name: string | null
  disabled: boolean
}

export interface ServiceAccountItem {
  id: number
  tenant_id: number
  name: string
  description: string | null
  status: string
  resource_owner: ServiceAccountOwner
  active_key_count: number
  last_used_at: string | null
  idle: boolean
  created_by: number | null
  create_time: string | null
  update_time: string | null
  disabled_at?: string | null
}

export interface ServiceAccountPage {
  data: ServiceAccountItem[]
  total: number
  idle_days: number
}

export interface ServiceAccountForm {
  name: string
  description?: string | null
  resource_owner_user_id: number
}

export interface DelegateScopeInput {
  subject_type: "user" | "department"
  subject_id: number
}

export interface ApiKeyItem {
  id: number
  subject_kind: string
  subject_id: number
  name: string
  key_mask: string
  scopes: string[]
  expires_at: string | null
  revoked_at: string | null
  last_used_at: string | null
  revoke_reason: string | null
  is_valid: boolean
  create_time: string | null
  delegate_scopes: DelegateScopeInput[]
}

export interface ApiKeyIssued extends ApiKeyItem {
  plaintext: string
}

export interface ApiKeyIssueForm {
  name: string
  scopes: string[]
  expires_at?: string | null
  delegate_scopes: DelegateScopeInput[]
}

export interface OpenApiScopeItem {
  code: string
  endpoints: string[]
}

export interface OpenApiScopeCatalog {
  scopes: OpenApiScopeItem[]
  open_platform_enabled: boolean
}

export interface PersonalTokenSetting {
  deployment_enabled: boolean
  pat_enabled: boolean
  effective_enabled: boolean
  pat_ttl_days: number
}

export interface PersonalTokenLedgerItem {
  id: number
  holder_user_id: number
  holder_name: string
  key_mask: string
  scopes: string[]
  expires_at: string | null
  revoked_at: string | null
  last_used_at: string | null
  revoke_reason: string | null
  is_valid: boolean
  holder_is_admin: boolean
  create_time: string | null
}

export interface PersonalTokenLedgerPage {
  data: PersonalTokenLedgerItem[]
  total: number
}
