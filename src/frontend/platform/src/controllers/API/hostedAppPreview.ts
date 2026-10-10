/**
 * The owner's preview instance of a release under review (PRD-1 RT-03 AC 11).
 *
 * While a publish request is pending, the owner can start a temporary instance
 * of the submitted version to see how it behaves on the platform. The instance
 * belongs to whoever started it: the owner cannot enter an approver's instance
 * and an approver cannot enter the owner's.
 *
 * The backend endpoints are shared with the approver's preview in the client's
 * approval centre; this module is the platform's own copy of the calls, because
 * the two apps must not import from each other.
 *
 * Every refusal (16264 – 16267) arrives as a business code inside a 200
 * envelope. All three calls pass `silent: true` so the interceptor neither
 * redirects nor drops the code, and each rejection is turned here into the
 * localized `api_errors` sentence. Callers therefore always receive a plain
 * message string, the same shape a non-silent call rejects with.
 */
import axios from "@/controllers/request"
import i18next from "i18next"
import { APPS_BASE } from "./hostedApp"

/**
 * The three states the backend reports. "Starting" is the caller's own: the
 * start call answers only once the instance is ready, so there is no
 * half-started state to read.
 */
export type PreviewState = "absent" | "running" | "reclaimed"

/** What ended the instance. `start_failed` means it never came up. */
export type PreviewReclaimReason =
  | "manual"
  | "approval_terminal"
  | "expired"
  | "start_failed"

/** Why no preview can be started; null when one can. */
export type PreviewBlockedReason = "no_image" | "settled"

export interface PreviewStatus {
  state: PreviewState
  session_id: string | null
  /** Where "open preview" goes. Null unless `state` is `running`. */
  entry_url: string | null
  expires_at: string | null
  reclaim_reason: PreviewReclaimReason | string | null
  runnable: boolean
  not_runnable_reason: PreviewBlockedReason | string | null
}

interface RejectedEnvelope {
  status_code?: unknown
  status_message?: unknown
}

/**
 * Localize a rejection from a `silent` call. The `api_errors` catalogue is the
 * only place the copy for 16264 – 16267 lives in all three languages;
 * `status_message` is the backend's Chinese sentence and is only a fallback.
 */
function toPreviewErrorMessage(error: unknown): string {
  if (typeof error === "string") return error
  if (error && typeof error === "object") {
    const { status_code: code, status_message: message } =
      error as RejectedEnvelope
    const fallback = typeof message === "string" ? message : ""
    if (typeof code === "number") {
      return i18next.t(`api_errors:${code}`, { defaultValue: fallback })
    }
    if (fallback) return fallback
    if (error instanceof Error) return error.message
  }
  return ""
}

async function call<T>(request: () => Promise<T>): Promise<T> {
  try {
    return await request()
  } catch (error) {
    throw toPreviewErrorMessage(error)
  }
}

const previewBase = (appId: string, versionId: string) =>
  `${APPS_BASE}/${encodeURIComponent(appId)}/versions/${encodeURIComponent(versionId)}/preview`

/** The caller's own instance of this version, if any, and whether one can start. */
export async function getPreviewStatusApi(
  appId: string,
  versionId: string,
): Promise<PreviewStatus> {
  return call(() =>
    axios.get(previewBase(appId, versionId), { silent: true }),
  )
}

/** Start one. An instance that is already running comes back unchanged. */
export async function startPreviewApi(
  appId: string,
  versionId: string,
): Promise<PreviewStatus> {
  return call(() =>
    axios.post(previewBase(appId, versionId), {}, { silent: true }),
  )
}

/** Reclaim the caller's own instance; the backend refuses anyone else's. */
export async function reclaimPreviewApi(
  appId: string,
  versionId: string,
  sessionId: string,
): Promise<PreviewStatus> {
  return call(() =>
    axios.delete(
      `${previewBase(appId, versionId)}/${encodeURIComponent(sessionId)}`,
      { silent: true },
    ),
  )
}
