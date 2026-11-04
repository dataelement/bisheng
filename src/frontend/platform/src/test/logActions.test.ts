import { describe, expect, it } from "vitest";

import { V2_ACTIONS, getActionsApi, getActionsByModuleApi } from "@/controllers/API/log";
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

  it("offers approval.exception.skip_node — it was whitelisted server-side only", async () => {
    // The backend surfaced this action but the filter never listed it, so the
    // event was written to audit_log and could not be found on the page. The
    // standing guard is `pnpm check-i18n` (it diffs V2_ACTIONS against the
    // Python tuple); this case is kept by name because it is the one that got
    // through.
    const actions = await getActionsApi();
    expect(actions).toEqual(
      expect.arrayContaining([
        {
          name: "log.eventTypeEnum.approvalExceptionSkipNode",
          value: "approval.exception.skip_node",
        },
      ]),
    );
  });

  it("labels open_api.api_key.* with the key the audit table actually looks up", async () => {
    // These six were hand-labelled `openApiKeyIssue` while the table derives
    // `openApiApiKeyIssue` from the row (`api_key` folds to two segments) — the
    // dropdown read fine and the table cell showed the raw action string. The
    // label is now derived from the value, so the two cannot disagree.
    const actions = await getActionsApi();
    const issue = actions.find((a) => a.value === "open_api.api_key.issue");
    expect(issue?.name).toBe(`log.eventTypeEnum.${actionToI18nKey("open_api.api_key.issue")}`);
    expect(issue?.name).toBe("log.eventTypeEnum.openApiApiKeyIssue");
  });

  it("derives every structured action's label instead of hand-writing it", async () => {
    const actions = await getActionsApi();
    for (const value of V2_ACTIONS) {
      const entry = actions.find((a) => a.value === value);
      expect(entry, `${value} missing from the filter list`).toBeDefined();
      expect(entry?.name).toBe(`log.eventTypeEnum.${actionToI18nKey(value)}`);
    }
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
