import type { ApprovalTaskItem } from "~/api/approval";

export type ApprovalTaskFilter = "pending_me" | "processed";

const FILE_CHANGE_SCENARIO_CODE = "knowledge_space_file_change_request";
const BUSINESS_PROJECTION_STATUSES = new Set([
  "pending",
  "approver_empty",
  "exception",
  "approved",
  "rejected",
  "withdrawn",
  "cancelled",
  "executing",
  "parsing",
  "parse_failed",
  "execute_failed",
  "executed",
  "published",
]);

function taskId(item: ApprovalTaskItem | null | undefined): number | null {
  const value = Number(item?.task_id ?? item?.id);
  return Number.isFinite(value) ? value : null;
}

export interface ApprovalTaskSelection {
  filter: ApprovalTaskFilter;
  visibleItems: ApprovalTaskItem[];
  selectedTaskId: number | null;
  resolvedPreferredTask: boolean;
}

/** Resolve a task only from the server-authorized list; a known historical id grants no visibility. */
export function resolveApprovalTaskSelection(
  items: ApprovalTaskItem[],
  currentFilter: ApprovalTaskFilter,
  preferredTaskId?: number | null,
  preferredInstanceId?: number | null,
): ApprovalTaskSelection {
  let preferred = preferredTaskId
    ? items.find((item) => taskId(item) === preferredTaskId) ?? null
    : null;
  if (!preferred && preferredInstanceId) {
    const matches = items.filter((item) => item.instance_id === preferredInstanceId);
    preferred = matches.find((item) => item.status === "pending") ?? matches[0] ?? null;
  }

  const filter = preferred
    ? (preferred.status === "pending" ? "pending_me" : "processed")
    : currentFilter;
  const visibleItems = filter === "pending_me"
    ? items.filter((item) => item.status === "pending")
    : items.filter((item) => item.status !== "pending");

  return {
    filter,
    visibleItems,
    selectedTaskId: taskId(preferred ?? visibleItems[0]),
    resolvedPreferredTask: Boolean(preferred),
  };
}

export interface FileChangeBusinessProjectionView {
  status: string;
  failureReason?: string;
}

export function parseFileChangeBusinessProjection(
  scenarioCode: string | undefined,
  value: unknown,
): FileChangeBusinessProjectionView | null {
  if (scenarioCode !== FILE_CHANGE_SCENARIO_CODE || !value || typeof value !== "object") {
    return null;
  }
  const projection = value as Record<string, unknown>;
  const status = typeof projection.status === "string" ? projection.status : "";
  if (!BUSINESS_PROJECTION_STATUSES.has(status)) return null;
  const failureReason = typeof projection.failure_reason === "string" && projection.failure_reason.trim()
    ? projection.failure_reason
    : undefined;
  return { status, failureReason };
}
