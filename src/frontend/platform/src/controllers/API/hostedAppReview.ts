/**
 * F055 T063 / T064 — the version diff read.
 *
 * Split out of `hostedApp.ts` for the same reason `hostedAppData.ts` was: that
 * file stays under the 600-line ceiling. The business codes
 * (`HOSTED_APP_ERROR.PUBLISH_*`) and the envelope helpers live there and are
 * what a caller branches on.
 *
 * The backend computes the diff: neither archive is downloadable and none is
 * sent here, so what arrives is a bounded, already-masked unified diff. The
 * same endpoint serves the client's review view — one data source behind the
 * one presentation component (AC-41).
 */
import axios from "@/controllers/request"
import { APPS_BASE } from "./hostedApp"

/** One version side of a diff, as `version_diff_service` reports it. */
export interface HostedAppDiffVersion {
  version_id: string
  version_no: number
  kind: "initial" | "iteration"
  terminal_state: "online" | "rejected" | "withdrawn" | null
  submitted_at: string | null
}

export interface HostedAppVersionDiff {
  base: HostedAppDiffVersion
  target: HostedAppDiffVersion
  role: "owner" | "super_admin" | "tenant_admin" | "approver"
  summary: {
    files_changed: number
    additions: number
    deletions: number
    truncated: boolean
  }
  files: {
    path: string
    change: "added" | "removed" | "modified"
    additions: number
    deletions: number
    comparable: boolean
    reason: string | null
  }[]
  patches: {
    path: string
    change: "added" | "removed" | "modified"
    patch: string | null
    truncated: boolean
    masked_secrets: number
  }[]
}

/**
 * What changed between two versions.
 *
 * `base` is the older side and `target` the newer, which is why AC-41's
 * "the iteration against the last published version" reads
 * `current_version_id` → `pending_version_id` and not the other way round.
 *
 * `silent: true` for the usual reason (`hostedApp.ts` header): a viewer the
 * backend refuses gets business code 16257 in a 200 envelope, and the caller
 * needs the code to tell "not allowed" from "broken".
 */
export async function getHostedAppVersionDiffApi(
  appId: string,
  baseVersionId: string,
  targetVersionId: string,
): Promise<HostedAppVersionDiff> {
  return await axios.get(
    `${APPS_BASE}/${appId}/versions/${baseVersionId}/diff/${targetVersionId}`,
    { silent: true },
  )
}
