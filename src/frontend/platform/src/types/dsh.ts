export type DshConfig =
    | { enabled: false }
    | { enabled: true; client_id: 'dsh-desktop'; contract_version: '0.4.0' }
export type DshDenial = {
    error: 'access_denied'
    redirect_uri: string
    state: string
}
export type DshAuthorization = {
    identity_ticket: string
    redirect_uri: string
    state: string
    expires_in: number
}
export type DshPage<T> = {
    items: T[]
    next_cursor: string | null
    has_more: boolean
    as_of?: string
}
export type DshSeat = {
    department_name?: string | null
    seat_id: string
    tenant_id: string
    user_id: string
    state: 'ASSIGNED' | 'REVOKED'
    grant_version: number
    username: string | null
    display_name: string | null
    profile_version: number | null
    profile_synced_at: string | null
    last_login_at: string | null
    last_seen_at: string | null
    active_session_count: number | null
    login_state: 'HAS_SESSIONS' | 'NO_SESSIONS' | 'UNAVAILABLE'
    created_at: string
}
export type DshLicense = {
    status: string
    source?: 'builtin' | 'signed' | null
    signed_license_status?: 'active' | 'not_granted' | 'license_invalid' | 'license_expired' | null
    seat_limit: number
    assigned: number
    available: number
    as_of: string
    license_id: string | null
    expires_at: string | null
}
export type DshUsage = {
    used: number | null
    limit: number
    remaining: number | null
    source: 'live' | 'persisted' | 'unavailable'
    as_of: string | null
    quota_state: 'available' | 'exhausted' | 'unavailable'
    /** Actual completed tokens by model, including models no longer configured. */
    models: Record<string, number> | null
    /** Independent monthly caps keyed by model ID; null means unavailable. */
    model_limits: Record<string, number> | null
    unknown_pending: number | null
    month: string
    billing_timezone: string
}
export type DshModelQuotaConfig = {
    /** Governed model ID, unique within this user policy. */
    model_id: number
    /** Monthly tokens for this model only; zero blocks its new requests. */
    monthly_token_limit: number
}
export type DshPolicy = {
    tenant_id: number
    available_models: { id: number; name: string; is_root_shared: boolean }[]
    available_models_source: 'live' | 'unavailable'
    last_call: DshLastCall | null
    last_call_source: 'persisted' | 'unavailable'
    pending_operation_id?: string | null
    version: number
    models: DshModelQuotaConfig[]
    quota_sync_state: 'PENDING' | 'READY' | 'FROZEN'
    usage: DshUsage | null
}
export type DshLastCall = {
    request_id: string
    model_id: number
    status: 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED' | 'USAGE_UNKNOWN'
    started_at: string | null
    finished_at: string | null
    total_tokens: number | null
    projected_at: string | null
}
export type DshPolicyInput = {
    operation_id: string
    expected_version: number
    enabled: boolean
    monthly_token_limit: number
}
export type DshOperation = {
    operation_id: string
    tenant_id: number
    user_id: number
    actor_user_id: number | null
    action: string
    status: 'PENDING' | 'PROCESSING' | 'SUCCEEDED' | 'FAILED'
    before_values: Record<string, unknown> | null
    after_values: Record<string, unknown> | null
    expected_grant_version: number | null
    expected_policy_version: number | null
    committed_at: string | null
    effective_at: string | null
    result_code: string | null
    result_payload: Record<string, unknown> | null
}
export type DshSeatQuery = {
    user_id?: string
    tenant_id?: string
    cursor?: string
    limit?: number
    keyword?: string
    seat_state?: 'ASSIGNED' | 'REVOKED'
    login_state?: 'HAS_SESSIONS' | 'NO_SESSIONS'
}
export type DshOperationRef = {
    model_id?: number
    operation_id: string
    tenant_id: string
    rejected?: boolean
    retry?: () => Promise<void>
}
export type DshModelAccessUser = {
    user_id: number
    user_name: string
    version: number
    enabled: boolean
    monthly_token_limit: number
    pending_operation_id: string | null
}

export type DshModelAccessPage = DshPage<DshModelAccessUser> & {
    tenant_id: number
    model: { id: number; name: string; is_root_shared: boolean }
}

export type DshUserPermissionSource = {
    subject_type: 'DEPARTMENT' | 'ROLE' | 'USER'
    subject_id: number
    name: string
    monthly_token_limit: number
    inherited: boolean
    winning: boolean
}
export type DshModelUserPermission = {
    access_status?: 'UNAUTHORIZED' | 'AUTHORIZED' | 'PENDING_LOGIN' | 'SEAT_LIMIT_REACHED' | 'REVOKED' | 'LICENSE_UNAVAILABLE' | 'UNAVAILABLE' | null
    user_id: number
    user_name: string
    direct_version: number
    direct_enabled: boolean
    direct_monthly_token_limit: number
    direct_pending_operation_id: string | null
    departments: Array<{ id: number; name: string; is_primary: boolean }>
    roles: Array<{ id: number; name: string }>
    authorized: boolean
    monthly_token_limit: number
    sources: DshUserPermissionSource[]
    department_match: 'DIRECT' | 'DESCENDANT' | null
}
export type DshModelUserPermissionPage = DshPage<DshModelUserPermission> & {
    tenant_id: number
    model: { id: number; name: string; is_root_shared: boolean }
}

export type DshSubjectType = 'DEPARTMENT' | 'ROLE'
export type DshSubjectPolicy = {
    subject_type: DshSubjectType
    subject_id: number
    name: string
    version: number
    enabled: boolean
    monthly_token_limit: number
}
export type DshDepartmentPolicy = DshSubjectPolicy & {
    subject_type: 'DEPARTMENT'
    parent_id: number | null
    depth: number
}
export type DshRolePolicy = DshSubjectPolicy & {
    subject_type: 'ROLE'
    role_type: 'global' | 'tenant'
    department_id: number | null
}
export type DshSubjectPolicyInventory = {
    tenant_id: number
    model_id: number
    departments: DshDepartmentPolicy[]
    roles: DshRolePolicy[]
}
export type DshSubjectPolicyInput = {
    expected_version: number
    enabled: boolean
    monthly_token_limit: number
}

export type DshUsageMetrics = {
    message_count: number
    qa_count: number
    failed_count: number
    cancelled_count: number
    running_count: number
    usage_unknown_count: number
    recorded_usage_count: number
    missing_usage_count: number
    input_tokens: number | null
    output_tokens: number | null
    total_tokens: number | null
}

export type DshUsageTimeBucket = DshUsageMetrics & {
    start_at: string
    end_at: string
    demo_tokens?: number
}

export type DshUsageTimeSummary = {
    demo?: { before: string; total_tokens: number }
    start_at: string
    end_at: string
    timezone: 'Asia/Shanghai'
    granularity: 'hour' | 'day'
    totals: DshUsageMetrics
    points: DshUsageTimeBucket[]
}

export type DshUsageOverviewUser = {
    user_id: number
    user_name: string
    department_id: number | null
    department_name: string | null
    metrics: DshUsageMetrics
}

export type DshUsageOverviewPage = {
    tenant_id: number
    start_at: string
    end_at: string
    timezone: 'Asia/Shanghai'
    department_id: number | null
    totals: DshUsageMetrics
    summary?: DshUsageTimeSummary | null
    items: DshUsageOverviewUser[]
    next_cursor: string | null
    has_more: boolean
}
