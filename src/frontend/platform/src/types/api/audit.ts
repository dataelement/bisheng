// System-audit rows as `/api/v1/audit` and `/api/v1/audit/export/data`
// return them after the F056 projection (AC-17 / AC-21 / AC-29 / AC-30).
// Shared by the API layer, the page renderers and their tests.

/** One audit row. Legacy v1 columns and structured v2 columns coexist. */
export interface AuditRow {
    id: string
    operator_id: number
    operator_name?: string | null
    create_time: string
    system_id?: string | null
    event_type?: string | null
    object_type?: string | null
    object_name?: string | null
    note?: string | null
    ip_address?: string | null
    tenant_id?: number | null
    action?: string | null
    target_type?: string | null
    target_id?: string | null
    reason?: string | null
    // F056 derived fields — never the raw metadata blob (AC-26).
    app_id?: string | null
    app_name?: string | null
    app_slug?: string | null
    app_state?: string | null
    app_owner_name?: string | null
    version_no?: number | null
    tenant_name?: string | null
    operator_kind?: 'service_account' | null
    operator_key_mask?: string | null
    // F003 organisation snapshot: null = not recorded, 0 = no department,
    // -1 = not applicable, > 0 = department id with its name path.
    operator_dept_id?: number | null
    operator_dept_path?: string | null
}

/** One department of the audit organisation picker (`/api/v1/audit/departments`). */
export interface AuditDeptNode {
    id: number
    dept_id: string
    external_id: string | null
    name: string
    path_name: string
    parent_id: number | null
    tenant_id: number
    has_children: boolean
}

export interface AuditDeptCandidates {
    active: AuditDeptNode[]
    archived: AuditDeptNode[]
    show_none: boolean
    show_unrecorded: boolean
}

/** What the organisation panel hands to a page's draft filters. */
export interface OrgSelection {
    deptIds: number[]
    includeDescendants: boolean
    includeNone: boolean
    includeUnrecorded: boolean
}

/** One option of the object-application selector (`/api/v1/audit/apps`). */
export interface AuditAppOption {
    id: string
    name: string
    slug: string
    state: string
    tenant_id?: number | null
}
