/** @jest-environment node */

import type { ApprovalTaskItem } from "~/api/approval";

import {
  parseFileChangeBusinessProjection,
  resolveApprovalTaskSelection,
} from "./approvalCenterFileChangeUtils";

function task(taskId: number, status = "pending"): ApprovalTaskItem {
  return {
    task_id: taskId,
    instance_id: taskId + 100,
    scenario_code: "knowledge_space_file_change_request",
    business_name: `file-${taskId}.pdf`,
    status,
  };
}

describe("approval center F046 decisions", () => {
  it("resolves selection only from the currently visible task projection", () => {
    const result = resolveApprovalTaskSelection([task(2)], "pending_me", 999, null);
    expect(result.selectedTaskId).toBe(2);
    expect(result.resolvedPreferredTask).toBe(false);
    expect(result.filter).toBe("pending_me");
  });

  it("selects the next pending task or an empty state after the current task disappears", () => {
    expect(resolveApprovalTaskSelection([task(2)], "pending_me").selectedTaskId).toBe(2);
    expect(resolveApprovalTaskSelection([], "pending_me").selectedTaskId).toBeNull();
  });

  it.each(["parsing", "parse_failed", "published", "execute_failed"])(
    "accepts the %s business projection and its failure reason",
    (status) => {
      expect(parseFileChangeBusinessProjection(
        "knowledge_space_file_change_request",
        { status, failure_reason: "reason" },
      )).toEqual({ status, failureReason: "reason" });
    },
  );

  it("ignores business projections belonging to another approval scenario", () => {
    expect(parseFileChangeBusinessProjection("menu_access_request", { status: "published" })).toBeNull();
  });
});
