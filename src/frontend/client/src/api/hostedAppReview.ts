/**
 * The review face of a hosted application's release (F055 AC-25 / AC-41).
 *
 * Four read-only endpoints behind one access rule (`ReviewAccess`): the
 * approver holding a task on *that* version gets in, alongside the owner, the
 * tenant administrator and a platform super admin. Everything else — someone
 * else's application, a version that does not exist, a snapshot that has been
 * swept — comes back as a business code inside a 200 envelope, never as a
 * 403/404, because this view is a panel inside the settings page and must keep
 * rendering.
 *
 * There is no endpoint that downloads the package, and there will not be one:
 * the source reaches the browser one masked file at a time, and the diff is
 * computed server-side.
 */
import request from "./request";

interface ApiResponse<T> {
  status_code: number;
  status_message: string;
  data: T;
}

/** Which door the caller came in through; an approver may read, not act. */
export type ReviewRole = "owner" | "super_admin" | "tenant_admin" | "approver";

/** 16257 no permission · 16253 no such version · 16256 snapshot gone · 16258 no such file. */
export const REVIEW_ERROR_CODES = {
  SNAPSHOT_UNAVAILABLE: 16256,
  FORBIDDEN: 16257,
  FILE_NOT_FOUND: 16258,
  VERSION_NOT_FOUND: 16253,
} as const;

export class HostedAppReviewError extends Error {
  constructor(
    readonly code: number,
    message: string,
  ) {
    super(message);
    this.name = "HostedAppReviewError";
  }
}

export interface ReviewVersion {
  version_id: string;
  version_no: number;
  kind: "initial" | "iteration";
  terminal_state: "online" | "rejected" | "withdrawn" | null;
  submitted_at: string | null;
}

export interface ReviewVersionRow extends ReviewVersion {
  is_current: boolean;
  is_pending: boolean;
}

export interface ReviewContext {
  version: ReviewVersion;
  role: ReviewRole;
  current_version_id: string | null;
  pending_version_id: string | null;
  versions: ReviewVersionRow[];
}

/** `reason` is the scanner's own verdict: `binary` or `too_large`, else null. */
export interface SnapshotEntry {
  path: string;
  name: string;
  type: "file" | "dir";
  size: number | null;
  previewable?: boolean;
  reason?: string | null;
}

export interface SnapshotTree {
  version: ReviewVersion;
  role: ReviewRole;
  entries: SnapshotEntry[];
  total_files: number;
  /** The package has more entries than the platform will list. */
  truncated: boolean;
}

export interface SnapshotFile {
  version: ReviewVersion;
  role: ReviewRole;
  path: string;
  size: number;
  previewable: boolean;
  reason: string | null;
  /** Null whenever `previewable` is false — those bytes never leave storage. */
  content: string | null;
  masked_secrets: number;
  line_count: number;
}

export interface VersionDiffResponse {
  base: ReviewVersion;
  target: ReviewVersion;
  role: ReviewRole;
  summary: {
    files_changed: number;
    additions: number;
    deletions: number;
    truncated: boolean;
  };
  files: {
    path: string;
    change: "added" | "removed" | "modified";
    additions: number;
    deletions: number;
    comparable: boolean;
    reason: string | null;
  }[];
  patches: {
    path: string;
    change: "added" | "removed" | "modified";
    patch: string | null;
    truncated: boolean;
    masked_secrets: number;
  }[];
}

function unwrap<T>(response: ApiResponse<T> | T): T {
  const envelope = response as ApiResponse<T>;
  if (envelope?.status_code != null && envelope.status_code !== 200) {
    throw new HostedAppReviewError(
      envelope.status_code,
      envelope.status_message || String(envelope.status_code),
    );
  }
  return (envelope?.data ?? response) as T;
}

const base = (appId: string, versionId: string) =>
  `/api/v1/apps/${encodeURIComponent(appId)}/versions/${encodeURIComponent(versionId)}`;

/** Version history plus the ids of the running and waiting versions. Reads no snapshot. */
export async function getReviewContextApi(appId: string, versionId: string): Promise<ReviewContext> {
  return unwrap(
    await request.get<ApiResponse<ReviewContext>>(`${base(appId, versionId)}/review-context`),
  );
}

/** Flat, path-sorted listing; directories are derived, so the tree is complete. */
export async function getSnapshotTreeApi(appId: string, versionId: string): Promise<SnapshotTree> {
  return unwrap(
    await request.get<ApiResponse<SnapshotTree>>(`${base(appId, versionId)}/snapshot/tree`),
  );
}

/** One file, secrets already masked server-side. */
export async function getSnapshotFileApi(
  appId: string,
  versionId: string,
  path: string,
): Promise<SnapshotFile> {
  return unwrap(
    await request.get<ApiResponse<SnapshotFile>>(
      `${base(appId, versionId)}/snapshot/file?path=${encodeURIComponent(path)}`,
    ),
  );
}

/** `baseVersionId` is the older side; AC-41 compares the published version to the pending one. */
export async function getVersionDiffApi(
  appId: string,
  baseVersionId: string,
  targetVersionId: string,
): Promise<VersionDiffResponse> {
  return unwrap(
    await request.get<ApiResponse<VersionDiffResponse>>(
      `${base(appId, baseVersionId)}/diff/${encodeURIComponent(targetVersionId)}`,
    ),
  );
}
