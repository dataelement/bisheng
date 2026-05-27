import { describe, expect, it } from "vitest";

import { getActionsApi, getActionsByModuleApi } from "@/controllers/API/log";
import { actionToI18nKey } from "@/pages/LogPage/systemLog";

describe("audit log actions", () => {
  it("includes approval revoke grant action in the global action list", async () => {
    const actions = await getActionsApi();
    expect(actions).toEqual(
      expect.arrayContaining([
        {
          name: "log.eventTypeEnum.approvalMenuAccessRevokeGrant",
          value: "approval.menu_access.revoke_grant",
        },
      ]),
    );
    expect(actions).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({ value: "approval.instance.resubmit" }),
      ]),
    );
  });

  it("folds dotted and snake_case action segments into camelCase i18n keys", () => {
    // Every entry whose value contains `_` previously rendered as a raw key
    // (e.g. `approvalExceptionAssign_approver`) because the converter only
    // split on `.`. Keep this in sync with the action list in log.ts.
    expect(actionToI18nKey("approval.exception.assign_approver")).toBe(
      "approvalExceptionAssignApprover",
    );
    expect(actionToI18nKey("approval.menu_access.revoke_grant")).toBe(
      "approvalMenuAccessRevokeGrant",
    );
    expect(actionToI18nKey("tenant.mount")).toBe("tenantMount");
    expect(actionToI18nKey("llm.server.create")).toBe("llmServerCreate");
  });

  it("keeps approval actions visible under the approval module filter", async () => {
    const actions = await getActionsByModuleApi("approval");
    expect(actions).toEqual(
      expect.arrayContaining([
        {
          name: "log.eventTypeEnum.approvalMenuAccessRevokeGrant",
          value: "approval.menu_access.revoke_grant",
        },
      ]),
    );
    expect(actions).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({ value: "approval.instance.resubmit" }),
      ]),
    );
  });
});
