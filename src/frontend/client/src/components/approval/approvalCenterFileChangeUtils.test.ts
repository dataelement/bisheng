/** @jest-environment node */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { ApprovalTaskItem } from "~/api/approval";

import {
  resolveApprovalTaskSelection,
  resolveFileChangeSpaceId,
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

  it("reads a positive space id only from the F046 safe payload snapshot", () => {
    expect(resolveFileChangeSpaceId({
      scenario_code: "knowledge_space_file_change_request",
      payload_snapshot: { space_id: 101 },
    })).toBe(101);
    expect(resolveFileChangeSpaceId({
      scenario_code: "menu_access_request",
      payload_snapshot: { space_id: 101 },
    })).toBeUndefined();
    expect(resolveFileChangeSpaceId({
      scenario_code: "knowledge_space_file_change_request",
      payload_snapshot: { space_id: 0 },
    })).toBeUndefined();
  });

  it("keeps approval API types free of business execution projections", () => {
    const apiSource = readFileSync(resolve(process.cwd(), "src/api/approval.ts"), "utf8");
    const forbidden = [
      "business_status_projection",
      "FileChangeBusinessStatusProjection",
      "executed_resource_id",
      "outbox_id",
      "outbox_status",
      "execution_token",
      "deferred",
    ];

    forbidden.forEach((token) => expect(apiSource).not.toContain(token));
  });

  it("does not parse business execution status inside approval-center utilities", () => {
    const utilitySource = readFileSync(
      resolve(process.cwd(), "src/components/approval/approvalCenterFileChangeUtils.ts"),
      "utf8",
    );
    const forbidden = [
      "parseFileChangeBusinessProjection",
      "BUSINESS_PROJECTION_STATUSES",
      "executing",
      "execute_failed",
      "published",
      "failure_reason",
    ];

    forbidden.forEach((token) => expect(utilitySource).not.toContain(token));
  });

  // The "business execution is not an approval fact" invariant moved to
  // messageApproval/notificationContent.test.tsx: routing now lives there, and it
  // is asserted on the exported action-code set instead of on file text.
});
