/**
 * The approval-time preview instance of a hosted application's release (F055 AC-26 … AC-29).
 *
 * An approver can run the version waiting to go live before deciding on it: the
 * platform brings up a throwaway instance with an empty database, injects the
 * approver's own identity, and takes it down again when the approval ends, when
 * the approver asks, or when it times out.
 *
 * Three calls, one shape. Every refusal — not an approver of this version, a
 * version that has no build yet, an instance that would not start — arrives as
 * a business code inside a 200 envelope, because this panel lives inside the
 * settings page and a real 403 would navigate the whole SPA away from the
 * request the approver was deciding on.
 *
 * There is no "list previews" call: an instance belongs to the person it was
 * raised for, so whose it is was never a question the client has to ask.
 */
import { createApiStatusError } from "~/utils/apiStatusError";
import request from "./request";

interface ApiResponse<T> {
  status_code: number;
  status_message: string;
  data: T;
}

/**
 * The four interface states of AC-26.
 *
 * `absent` is "you have not tried this yet" and `reclaimed` is "your trial is
 * over" — different sentences, so they are different values rather than one
 * nullable session. 「拉起中」 is the client's own: the platform answers only
 * once the instance is ready, so there is no half-started state to report.
 */
export type PreviewState = "absent" | "running" | "reclaimed";

/** Which of the three triggers ended it — the panel says so, they read differently. */
export type PreviewReclaimReason = "manual" | "approval_terminal" | "expired";

/** Why a preview cannot be raised at all; `null` when it can. */
export type PreviewBlockedReason = "no_image" | "settled";

export interface PreviewStatus {
  state: PreviewState;
  session_id: string | null;
  /** Where 「打开预览」 goes. Null unless `state` is `running`. */
  entry_url: string | null;
  expires_at: string | null;
  reclaim_reason: PreviewReclaimReason | null;
  runnable: boolean;
  not_runnable_reason: PreviewBlockedReason | null;
}

/**
 * Business codes ride in a 200 envelope, so nothing rejects on its own here.
 * The message goes through `createApiStatusError`, the only path that consults
 * the `api_errors` catalogue: `status_message` is the backend's own Chinese
 * sentence, and showing it directly would put Chinese in front of an `en` / `ja`
 * approver even though all three languages are written and shipped.
 */
function unwrap<T>(response: ApiResponse<T> | T): T {
  const envelope = response as ApiResponse<T>;
  if (envelope?.status_code != null && envelope.status_code !== 200) {
    throw createApiStatusError(envelope);
  }
  return (envelope?.data ?? response) as T;
}

const base = (appId: string, versionId: string) =>
  `/api/v1/apps/${encodeURIComponent(appId)}/versions/${encodeURIComponent(versionId)}/preview`;

/** This approver's own instance, if there is one, plus whether one is possible. */
export async function getPreviewStatusApi(appId: string, versionId: string): Promise<PreviewStatus> {
  return unwrap(await request.get<ApiResponse<PreviewStatus>>(base(appId, versionId)));
}

/** Raise one. An instance that is already running comes back unchanged. */
export async function startPreviewApi(appId: string, versionId: string): Promise<PreviewStatus> {
  // `request.post` is untyped (it returns `response.data` as `any`), so the
  // envelope type is asserted here rather than at the call — the alternative is
  // an `any` leaking into every caller of this module.
  return unwrap((await request.post(base(appId, versionId), {})) as ApiResponse<PreviewStatus>);
}

/** 「手动回收」. Only one's own instance; the backend refuses anybody else's. */
export async function reclaimPreviewApi(
  appId: string,
  versionId: string,
  sessionId: string,
): Promise<PreviewStatus> {
  return unwrap(
    await request.delete<ApiResponse<PreviewStatus>>(
      `${base(appId, versionId)}/${encodeURIComponent(sessionId)}`,
    ),
  );
}
