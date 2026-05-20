import { describe, expect, it } from "vitest";

import { getActionsApi, getActionsByModuleApi } from "@/controllers/API/log";

describe("audit log actions", () => {
  it("includes approval resubmit and revoke grant actions in the global action list", async () => {
    const actions = await getActionsApi();
    expect(actions).toEqual(
      expect.arrayContaining([
        {
          name: "log.eventTypeEnum.approvalInstanceResubmit",
          value: "approval.instance.resubmit",
        },
        {
          name: "log.eventTypeEnum.approvalMenuAccessRevokeGrant",
          value: "approval.menu_access.revoke_grant",
        },
      ]),
    );
  });

  it("keeps new approval actions visible under the approval module filter", async () => {
    const actions = await getActionsByModuleApi("approval");
    expect(actions).toEqual(
      expect.arrayContaining([
        {
          name: "log.eventTypeEnum.approvalInstanceResubmit",
          value: "approval.instance.resubmit",
        },
        {
          name: "log.eventTypeEnum.approvalMenuAccessRevokeGrant",
          value: "approval.menu_access.revoke_grant",
        },
      ]),
    );
  });
});
