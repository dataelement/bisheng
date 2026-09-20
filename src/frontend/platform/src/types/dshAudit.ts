export const auditActions = [
    'REVOKE',
    'REASSIGN',
    'UPDATE_POLICY',
    'UPDATE_DEPARTMENT_POLICY',
    'UPDATE_ROLE_POLICY',
    'SYNC_PROFILE',
    'RECONCILE_USAGE',
] as const
export const auditStatuses = [
    'PENDING',
    'PROCESSING',
    'SUCCEEDED',
    'FAILED',
] as const
export type DshAuditAction = (typeof auditActions)[number]
export type DshAuditStatus = (typeof auditStatuses)[number]
export type DshAuditValues = Record<string, string | number | boolean | null>
export interface DshAuditRecord {
    id: string
    created_at: string
    action: DshAuditAction
    status: DshAuditStatus
    actor_id: number | null
    actor_name: string | null
    target_type: 'USER' | 'DEPARTMENT' | 'ROLE'
    target_id: number
    target_name: string | null
    model_id: number | null
    model_name: string | null
    before_values: DshAuditValues
    after_values: DshAuditValues
    requested_values: DshAuditValues
    result_code: string | null
}
export interface DshAuditPage {
    data: DshAuditRecord[]
    page_size: number
    has_more: boolean
    next_cursor: string | null
}
export interface DshAuditQuery {
    cursor?: string
    limit: number
    action?: DshAuditAction
    status?: DshAuditStatus
}
