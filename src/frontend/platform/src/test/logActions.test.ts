import { describe, expect, it } from "vitest";

import { getActionsApi, getActionsByModuleApi, getModulesApi } from "@/controllers/API/log";
import { toggleFilterValue } from "@/pages/LogPage/ClearableFilterSelect";
import { actionToI18nKey, renderRemark } from "@/pages/LogPage/systemLog";

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
    expect(actionToI18nKey("filelib_sync.upload.success")).toBe("filelibSyncUploadSuccess");
    expect(actionToI18nKey("filelib_sync.inspection_standard.batch.failed")).toBe(
      "filelibSyncInspectionStandardBatchFailed",
    );
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

  it("keeps filelib sync actions visible under the filelib_sync module filter", async () => {
    const actions = await getActionsByModuleApi("filelib_sync");
    expect(actions).toEqual(
      expect.arrayContaining([
        {
          name: "log.eventTypeEnum.filelibSyncUploadSuccess",
          value: "filelib_sync.upload.success",
        },
        {
          name: "log.eventTypeEnum.filelibSyncUploadFailed",
          value: "filelib_sync.upload.failed",
        },
      ]),
    );
  });

  it("lists points rule updates under the points module", async () => {
    const modules = await getModulesApi();
    expect(modules.data).toEqual(
      expect.arrayContaining([{ name: "log.systemIdEnum.points", value: "points" }]),
    );
    const actions = await getActionsByModuleApi("points");
    expect(actions).toEqual([
      { name: "log.eventTypeEnum.pointsRuleUpdate", value: "points.rule.update" },
    ]);
  });

  it("shows points rule field changes in the audit remark", () => {
    const dict: Record<string, string> = {
      "log.pointsRuleField.score": "分值",
      "log.pointsRuleField.display_name": "展示名称",
      "log.pointsRuleField.status": "状态",
      "log.pointsRuleValue.empty": "空",
      "log.pointsRuleValue.enabled": "启用",
      "log.pointsRuleValue.disabled": "禁用",
      "log.pointsRuleChangeLine": "{{field}}：{{before}} → {{after}}",
      "log.objectTypeEnum.none": "无",
    };
    const t = (key: string, opts?: Record<string, string>) => {
      const template = dict[key] ?? opts?.defaultValue ?? key;
      return template
        .replace("{{field}}", opts?.field ?? "")
        .replace("{{before}}", opts?.before ?? "")
        .replace("{{after}}", opts?.after ?? "");
    };

    expect(
      renderRemark(
        {
          action: "points.rule.update",
          audit_metadata: {
            changes: [
              { field: "score", before: 30, after: 50 },
              { field: "display_name", before: "上传文档", after: "公共库上传" },
              { field: "status", before: "enabled", after: "disabled" },
            ],
          },
        },
        t,
      ),
    ).toBe("分值：30 → 50\n展示名称：上传文档 → 公共库上传\n状态：启用 → 禁用");

    expect(
      renderRemark(
        {
          action: "points.rule.update",
          metadata: {
            changes: [{ field: "score_expr", before: { mode: "fixed", score: 30 }, after: { mode: "tier" } }],
          },
        },
        t,
      ),
    ).toBe('score_expr：{"mode":"fixed","score":30} → {"mode":"tier"}');

    expect(renderRemark({ action: "points.rule.update", metadata: { changes: [] }, note: "旧备注" }, t)).toBe("旧备注");
    expect(renderRemark({ note: "编辑后仍保留" }, t)).toBe("编辑后仍保留".replace("编辑后", "\n编辑后"));
  });

  it("clears a filter when the already-selected option is clicked again", () => {
    expect(toggleFilterValue("approval", "approval")).toBe("");
    expect(toggleFilterValue("approval", "tenant")).toBe("tenant");
    expect(toggleFilterValue("", "approval")).toBe("approval");
  });
});
