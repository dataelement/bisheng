// Types for F021 Org Sync (WeCom / Feishu / Generic API).

export type OrgSyncProvider = "wecom" | "feishu" | "dingtalk" | "generic_api"

export type OrgSyncStatus = "active" | "disabled" | "deleted"

export type OrgSyncSyncStatus = "idle" | "running"

export type OrgSyncRunStatus = "running" | "success" | "partial" | "failed"

export type OrgSyncScheduleType = "manual" | "cron"

export interface OrgSyncConfig {
  id: number
  provider: OrgSyncProvider
  config_name: string
  auth_type: string
  auth_config: Record<string, unknown> // Masked for secret fields
  sync_scope: Record<string, unknown> | null
  schedule_type: OrgSyncScheduleType
  cron_expression: string | null
  sync_status: OrgSyncSyncStatus
  last_sync_at: string | null
  last_sync_result: OrgSyncRunStatus | null
  status: OrgSyncStatus
  create_user: number | null
  create_time: string | null
  update_time: string | null
}

export interface OrgSyncConfigCreate {
  provider: OrgSyncProvider
  config_name: string
  auth_type: string
  auth_config: Record<string, unknown>
  sync_scope?: Record<string, unknown> | null
  schedule_type?: OrgSyncScheduleType
  cron_expression?: string | null
}

export interface OrgSyncConfigUpdate {
  auth_type?: string
  auth_config?: Record<string, unknown>
  sync_scope?: Record<string, unknown> | null
  schedule_type?: OrgSyncScheduleType
  cron_expression?: string | null
  status?: OrgSyncStatus
  config_name?: string
}

export interface OrgSyncTestResult {
  connected: boolean
  org_name: string
  total_depts: number
  total_members: number
}

export interface OrgSyncLog {
  id: number
  config_id: number
  trigger_type: string
  trigger_user: number | null
  status: OrgSyncRunStatus
  dept_created: number
  dept_updated: number
  dept_archived: number
  member_created: number
  member_updated: number
  member_disabled: number
  member_reactivated: number
  error_details: Array<Record<string, unknown>> | null
  start_time: string | null
  end_time: string | null
  create_time: string | null
}

export interface OrgSyncLogPage {
  data: OrgSyncLog[]
  total: number
}

export interface OrgSyncRemoteNode {
  external_id: string
  name: string
  children: OrgSyncRemoteNode[]
}

// WeCom-specific auth_config shape (used by the WeComFieldSet).
export interface WeComAuthConfig {
  corpid: string
  corpsecret: string
  agent_id: string
  allow_dept_ids?: number[]
}
