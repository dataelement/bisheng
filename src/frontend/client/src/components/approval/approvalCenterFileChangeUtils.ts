import type { ApprovalTaskItem } from "~/api/approval";

export type ApprovalTaskFilter = "pending_me" | "processed";

export const FILE_CHANGE_SCENARIO_CODE = "knowledge_space_file_change_request";

interface FileChangeSafeSnapshot {
  scenario_code?: string;
  payload_snapshot?: Record<string, unknown>;
}

export function resolveFileChangeSpaceId(
  detail: FileChangeSafeSnapshot | null | undefined,
): number | undefined {
  if (detail?.scenario_code !== FILE_CHANGE_SCENARIO_CODE) return undefined;
  const spaceId = Number(detail.payload_snapshot?.space_id);
  return Number.isSafeInteger(spaceId) && spaceId > 0 ? spaceId : undefined;
}

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
