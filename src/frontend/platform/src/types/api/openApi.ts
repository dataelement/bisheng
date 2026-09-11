export interface ServiceAccountOwner {
  user_id: number
  user_name: string | null
  disabled: boolean
}

export type ServiceAccountStatus = "enabled" | "disabled"

export interface ServiceAccountDelegateScope {
  subject_type: "user" | "department"
  subject_id: number
  subject_name: string | null
}

export interface ServiceAccountItem {
  id: number
  tenant_id: number
  name: string
  description: string | null
  status: ServiceAccountStatus
  resource_owner: ServiceAccountOwner
  active_key_count: number
  has_delegate: boolean
  delegate_scopes: ServiceAccountDelegateScope[]
  last_used_at: string | null
  idle: boolean
  created_by: number | null
  creator_name: string | null
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

export interface ServiceAccountDeleteResult {
  id: number
  grants: ServiceAccountResourceGrant[]
}

export interface ServiceAccountResourceGrant {
  resource_type: string
  resource_id: string
  resource_name: string
  model_key: string
  model_name: string
  assignee_id: string
  assignee_version: number
  source_type: string
  granted_at: string | null
  protected: boolean
  editable: boolean
}

export interface ServiceAccountGrantableResource {
  resource_type: string
  resource_id: string
  resource_name: string
  mode: "INHERIT" | "CUSTOM"
  resource_version: number
}

export interface DelegateScopeInput {
  subject_type: "user" | "department"
  subject_id: number
}

export interface DelegateScopeItem extends DelegateScopeInput {
  subject_name: string | null
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
  delegate_scopes: DelegateScopeItem[]
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

export interface ApiKeyUpdateForm {
  name?: string
  scopes?: string[]
  expires_at?: string | null
  delegate_scopes?: DelegateScopeInput[]
}

export interface OpenApiScopeItem {
  code: string
  group: string
  label_key: string
  desc_key: string
  endpoints: Array<{
    method: string
    path: string
  }>
  hint_keys: string[]
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
