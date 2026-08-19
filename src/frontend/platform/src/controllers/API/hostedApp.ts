/**
 * F054 hosted applications — every HTTP call the platform UI makes for them.
 *
 * Three things about this module are load bearing:
 *
 * - **One place for the wire shapes.** The card's read-only version dropdown,
 *   the detail page's version tab and the publish tab all consume the same
 *   payloads; letting each invent its own shape is how the three drift.
 * - **Refusals arrive inside a 200 envelope.** The backend answers "you may not
 *   read these logs" with business code 16161, never HTTP 403/404, because the
 *   platform response interceptor turns a 403/404 on a GET into a full-page
 *   redirect to `/403` — one forbidden tab would cost the whole detail page.
 *   Reads that a non-owner can legitimately hit therefore pass `silent: true`
 *   so the caller receives the envelope and can render an inline notice.
 * - **`entry_url` comes from the backend, whole.** Never compose it from
 *   `location.origin`: in dev the SPA runs on :3001 and `/apps` is not in the
 *   vite proxy, so a composed link would be dead.
 */
import axios from "@/controllers/request"

/** The five application states (design D8 / AC-03). */
export type HostedAppState =
  | "draft"
  | "online"
  | "pending_capacity"
  | "stopped"
  | "deleted"

/** Instance phase reported by the orchestrator — deployment-shape agnostic. */
export type HostedAppPhase =
  | "pending"
  | "building"
  | "starting"
  | "running"
  | "unhealthy"
  | "stopped"
  | "failed"

export interface HostedAppDetail {
  app_id: string
  slug: string
  name: string
  description: string | null
  logo: string | null
  state: HostedAppState
  owner_user_id: number
  tenant_id: number
  current_version_id: string | null
  pending_version_id: string | null
  /** Full address of the entry, built by the backend. Do not compose it. */
  entry_url: string
  create_time: string | null
  update_time: string | null
}

export interface HostedAppInstance {
  instance_id: string | null
  phase: HostedAppPhase
  health: string | null
  current_version_id: string | null
  started_at: string | null
  restart_count: number
  last_probe_at: string | null
}

export interface HostedAppVersion {
  version_id: string
  version_no: number
  kind: "initial" | "iteration"
  terminal_state: "online" | "rejected" | "withdrawn" | null
  submitted_at: string | null
  is_current: boolean
  is_pending: boolean
}

/** `lines` are the application's own stdout/stderr, newest last. */
export interface HostedAppLogs {
  lines: string[]
}

export interface HostedAppPreflightItem {
  name: string
  ok: boolean
  detail?: string
}

export interface HostedAppRuntimeStatus {
  backend_available: boolean
  supported_runtimes: string[]
  capacity: Record<string, unknown>
  preflight: HostedAppPreflightItem[]
}

/**
 * Result of a state action.
 *
 * `ok: false` is still a *successful request*: "parked for capacity" and "start
 * failed" are outcomes the UI has to render, and they carry `state` + `reason`.
 * Treating them as errors would drop both.
 */
export interface HostedAppActionResult {
  app_id: string
  state: HostedAppState
  ok: boolean
  reason: string | null
  version_id: string | null
  detail?: Record<string, unknown> | null
}

export interface HostedAppMetaPatch {
  name?: string
  description?: string
  /** MinIO object name, never a presigned URL. */
  logo?: string
}

export interface HostedAppLogQuery {
  /** 1–5000, backend default 500. */
  tail?: number
  /** Epoch seconds, or a relative window such as `30m` / `2h` / `7d`. */
  since?: string
  /** Case-insensitive substring, filtered after `tail`. */
  keyword?: string
}

const APPS_BASE = "/api/v1/apps"

// ---------------------------------------------------------------------------
// reads
// ---------------------------------------------------------------------------

export async function getHostedAppApi(appId: string): Promise<HostedAppDetail> {
  return await axios.get(`${APPS_BASE}/${appId}`, { silent: true })
}

export async function getHostedAppInstanceApi(
  appId: string,
): Promise<HostedAppInstance> {
  return await axios.get(`${APPS_BASE}/${appId}/instance`, { silent: true })
}

/**
 * Read-only version list, newest first.
 *
 * The source is `app_version`. It is *not* the `version_list` the app list
 * attaches to flow rows — that one is always empty for a hosted app, and the
 * component built for it writes back to a workflow when a version is picked.
 */
export async function getHostedAppVersionsApi(
  appId: string,
): Promise<HostedAppVersion[]> {
  return await axios.get(`${APPS_BASE}/${appId}/versions`, { silent: true })
}

export async function getHostedAppLogsApi(
  appId: string,
  query: HostedAppLogQuery = {},
): Promise<HostedAppLogs> {
  const params = new URLSearchParams()
  if (query.tail !== undefined) params.set("tail", String(query.tail))
  if (query.since) params.set("since", query.since)
  if (query.keyword) params.set("keyword", query.keyword)
  const qs = params.toString()
  return await axios.get(
    `${APPS_BASE}/${appId}/logs${qs ? `?${qs}` : ""}`,
    { silent: true },
  )
}

/** Super admin only; describes the host, not one application. */
export async function getHostedAppRuntimeStatusApi(): Promise<HostedAppRuntimeStatus> {
  return await axios.get(`${APPS_BASE}/runtime-status`, { silent: true })
}

export async function listHostedAppsApi(): Promise<HostedAppDetail[]> {
  return await axios.get(APPS_BASE, { silent: true })
}

// ---------------------------------------------------------------------------
// writes
// ---------------------------------------------------------------------------

/** AC-06 — metadata only: no state change, no version record. */
export async function updateHostedAppMetaApi(
  appId: string,
  patch: HostedAppMetaPatch,
): Promise<HostedAppDetail> {
  return await axios.patch(`${APPS_BASE}/${appId}`, patch)
}

export async function deleteHostedAppApi(
  appId: string,
): Promise<HostedAppActionResult> {
  return await axios.delete(`${APPS_BASE}/${appId}`)
}

export async function publishHostedAppApi(
  appId: string,
): Promise<HostedAppActionResult> {
  return await axios.post(`${APPS_BASE}/${appId}/actions/publish`)
}

/** Retry a parked application without a second approval. */
export async function manualPublishHostedAppApi(
  appId: string,
): Promise<HostedAppActionResult> {
  return await axios.post(`${APPS_BASE}/${appId}/actions/manual-publish`)
}

export async function stopHostedAppApi(
  appId: string,
): Promise<HostedAppActionResult> {
  return await axios.post(`${APPS_BASE}/${appId}/actions/stop`)
}

export async function resumeHostedAppApi(
  appId: string,
): Promise<HostedAppActionResult> {
  return await axios.post(`${APPS_BASE}/${appId}/actions/resume`)
}

// ---------------------------------------------------------------------------
// publish pipeline (F055)
// ---------------------------------------------------------------------------

/** Why an approved application is parked instead of running. */
export type HostedAppPendingReason = "capacity" | "deploy_failed"

/**
 * Approval-instance status, mirroring the approval centre's own vocabulary.
 *
 * The union is written out so the card's label map is exhaustive, but the
 * payload field stays widened to `string`: the approval centre owns these
 * values and may add one, and a status the card cannot name must degrade to a
 * neutral label rather than render nothing.
 */
export type HostedAppApprovalStatus =
  | "pending"
  | "approved"
  | "executing"
  | "executed"
  | "rejected"
  | "exception"
  | "withdrawn"
  | "cancelled"
  | "execute_failed"

export interface HostedAppApproval {
  instance_id: number
  status: HostedAppApprovalStatus | string
  submitted_at: string | null
  decided_at: string | null
  /** Sent in full by the backend, and rendered in full here (AC-33). */
  reject_reason: string | null
  approver_names: string[]
}

export interface HostedAppDeploymentRef {
  id: string | null
  stage: string | null
  status: string | null
  failure: Record<string, unknown> | null
}

export interface HostedAppTier {
  code: string | null
  name: string | null
  cpu_millicores: number | null
  memory_mb: number | null
  enabled?: boolean
}

/**
 * Breaking table-structure change awaiting confirmation.
 *
 * The backend always sends `null` in this release (the capability/schema wave
 * is deferred). The shape is declared now so the publish face can keep a slot
 * for it without changing type when the wave lands.
 */
export interface HostedAppSchemaChange {
  summary?: string | null
  details?: string[] | null
}

/**
 * `GET /api/v1/apps/{id}/publish-status` — the single release read model
 * (AC-38), shared with the MCP status tool.
 */
export interface HostedAppPublishStatus {
  app_id: string
  app_state: HostedAppState
  pending_reason: HostedAppPendingReason | null
  current_version: HostedAppVersion | null
  pending_version: HostedAppVersion | null
  deployment: HostedAppDeploymentRef | null
  approval: HostedAppApproval | null
  tier: HostedAppTier | null
  /** Deferred capability wave; always empty in this release. */
  capabilities: unknown[]
  schema_change: HostedAppSchemaChange | null
  can: {
    withdraw: boolean
    manual_publish: boolean
    /** AC-06 — always false while every application arrives through the CLI. */
    submit: boolean
  }
}

/**
 * Outcome of a pipeline manual publish.
 *
 * Not a `HostedAppActionResult`: this endpoint answers with the pipeline's own
 * `status` word (`online` / `pending_capacity` / `pending_deploy_failed`),
 * which carries the parked *reason* that `ok: false` alone would lose.
 */
export interface HostedAppPublishOutcome {
  status: "online" | "pending_capacity" | "pending_deploy_failed" | string
  app_id: string
  version_id: string
  app_state: HostedAppState
  reason?: string | null
}

/**
 * The release read model (AC-38).
 *
 * `silent: true` is mandatory. A viewer who is neither owner nor administrator
 * is refused with business code 16254 inside a 200 envelope; without `silent`
 * the interceptor swallows the code (the caller receives a bare message string)
 * and toasts on every page open, and any future 403/404 on this GET would
 * navigate the whole SPA to `/403` — losing the detail page over one card.
 */
export async function getPublishStatusApi(
  appId: string,
): Promise<HostedAppPublishStatus> {
  return await axios.get(`${APPS_BASE}/${appId}/publish-status`, {
    silent: true,
  })
}

/**
 * Retry a parked release through the pipeline (AC-32).
 *
 * Distinct from `manualPublishHostedAppApi`, which is F054's state action: this
 * one adds the owner-only pre-check and latches the version record's terminal
 * state, so it is what the publish face calls.
 */
export async function manualPublishViaPipelineApi(
  appId: string,
): Promise<HostedAppPublishOutcome> {
  return await axios.post(`${APPS_BASE}/${appId}/publish/manual-publish`)
}

/**
 * Withdraw an in-flight publish request (AC-34).
 *
 * Deliberately the approval centre's own endpoint rather than a publish-side
 * one: "only the applicant may withdraw" is already enforced there, and a
 * second endpoint would be a second place for that rule to drift.
 *
 * The body is required even when there is no reason — the endpoint declares a
 * pydantic model without a default, so a bodyless POST is a 422.
 */
export async function withdrawApprovalApi(
  instanceId: number,
  reason?: string,
): Promise<unknown> {
  return await axios.post(
    `/api/v1/approval/instances/${instanceId}/withdraw`,
    reason ? { reason } : {},
  )
}

// ---------------------------------------------------------------------------
// business-code helpers
// ---------------------------------------------------------------------------

/**
 * Codes the UI branches on. Everything else is a generic failure.
 *
 * Two bands, and they are not interchangeable: **161xx** is F054 (the hosted
 * application itself — state actions, logs, runtime layer), **162xx** is F055
 * (the publish pipeline — approval, version records, tiers). The same
 * condition genuinely exists in both — 16125 is "a state action was refused
 * for capacity", 16226 is "a publish parked for capacity" — and the copy
 * differs, so collapsing them would make one of the two messages wrong.
 */
export const HOSTED_APP_ERROR = {
  NOT_FOUND: 16101,
  STATE_CONFLICT: 16102,
  ONLINE_CANNOT_DELETE: 16104,
  OWNER_ONLY: 16105,
  MANAGE_FORBIDDEN: 16106,
  ORCHESTRATOR_UNAVAILABLE: 16121,
  CAPACITY_INSUFFICIENT: 16125,
  LOG_FORBIDDEN: 16161,
  LAYER_NOT_DEPLOYED: 16181,
  // 162xx — publish pipeline (F055).
  PUBLISH_LAYER_DISABLED: 16207,
  PUBLISH_CAPACITY_INSUFFICIENT: 16226,
  PUBLISH_APPROVAL_IN_FLIGHT: 16251,
  PUBLISH_PENDING_ONLINE: 16252,
  PUBLISH_VERSION_NOT_FOUND: 16253,
  PUBLISH_OWNER_ONLY: 16254,
  PUBLISH_STATE_CONFLICT: 16255,
} as const

/**
 * Business code of a rejection raised by a `silent: true` call.
 *
 * Without `silent` the interceptor rejects with a plain message string and the
 * code is gone, which is why every read that needs to distinguish "forbidden"
 * from "broken" asks for the envelope.
 */
export function getHostedAppErrorCode(error: unknown): number | undefined {
  if (error && typeof error === "object" && "status_code" in error) {
    const code = (error as { status_code?: unknown }).status_code
    if (typeof code === "number") return code
  }
  return undefined
}

/** Human-readable text carried by a rejected envelope, if any. */
export function getHostedAppErrorMessage(error: unknown): string {
  if (error && typeof error === "object" && "status_message" in error) {
    const message = (error as { status_message?: unknown }).status_message
    if (typeof message === "string") return message
  }
  if (typeof error === "string") return error
  return ""
}
