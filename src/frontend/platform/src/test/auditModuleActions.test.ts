// F003 T010: explicit module → action map and the five legacy actions that
// had no filter entry (spec AC-01 / AC-03).

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { getActionsApi, getActionsByModuleApi } from "@/controllers/API/log";

const ADDED = [
  "update_sandbox_conf",
  "link_file_version",
  "set_primary_version",
  "delete_file_version",
  "dismiss_similar_file",
];

const values = async (moduleId: string) => (await getActionsByModuleApi(moduleId)).map((a) => a.value);

describe("audit module → action map", () => {
  it("puts tools and the sandbox under system", async () => {
    expect(await values("system")).toEqual(
      expect.arrayContaining(["add_tool", "update_tool", "delete_tool", "update_sandbox_conf", "user_login"]),
    );
  });

  it("puts the four file-version actions under knowledge, without knowledge-space ones", async () => {
    const knowledge = await values("knowledge");
    expect(knowledge).toEqual(
      expect.arrayContaining(["link_file_version", "set_primary_version", "delete_file_version", "dismiss_similar_file"]),
    );
    expect(knowledge.some((v) => v.includes("knowledge_space"))).toBe(false);
  });

  it("keeps knowledge-space actions in their own module", async () => {
    expect(await values("knowledge_space")).toEqual(["create_knowledge_space", "delete_knowledge_space"]);
  });

  it("files the 17 sensitive v2 actions by prefix", async () => {
    expect(await values("tenant")).toEqual(["tenant.mount", "tenant.unmount", "tenant.disable"]);
    expect(await values("llm")).toEqual(["llm.server.create", "llm.server.update", "llm.server.delete"]);
    expect(await values("approval")).toEqual(expect.arrayContaining(["approval.task.approve", "approval.task.reject"]));
    expect(await values("open_api")).toEqual(expect.arrayContaining(["open_api.api_key.issue", "open_api.api_key.revoke"]));
    expect(await values("app")).toEqual(
      expect.arrayContaining(["app.publish", "app.stop", "app.delete", "app.data_export", "app.data_restore", "app.visibility_change", "app.secret.set"]),
    );
  });

  it("gives every legacy action exactly one module", async () => {
    const modules = ["chat", "build", "knowledge", "system", "dashboard", "subscription", "knowledge_space"];
    const filed = (await Promise.all(modules.map(values))).flat();
    const legacy = (await getActionsApi()).map((a) => a.value).filter((v) => !v.includes("."));
    expect([...filed].sort()).toEqual([...legacy].sort());
  });

  it("returns nothing for an unknown module", async () => {
    expect(await values("nope")).toEqual([]);
  });
});

describe("the five added actions", () => {
  it("are offered by the action filter", async () => {
    const all = (await getActionsApi()).map((a) => a.value);
    expect(all).toEqual(expect.arrayContaining(ADDED));
  });

  it("have a caption in every language, never the raw value", () => {
    for (const locale of ["zh-Hans", "en-US", "ja"]) {
      const bs = JSON.parse(readFileSync(resolve(__dirname, `../../public/locales/${locale}/bs.json`), "utf-8"));
      for (const action of ADDED) {
        const caption = bs.log.eventTypeEnum[action];
        expect(caption, `${locale} ${action}`).toBeTruthy();
        expect(caption).not.toBe(action);
      }
    }
  });
});

// The 17 sensitive actions and the organisation column use the wording from
// 审计功能优化. The fourth usage type is shown as 深度研究: the requirements
// document says 任务模式, and the audit page was later confirmed to use the
// product name instead. The stored filter value stays `task`.
const SENSITIVE_CAPTIONS: Record<string, Record<string, string>> = {
  "zh-Hans": {
    tenantMount: "部门挂载租户",
    tenantUnmount: "解除部门租户挂载",
    tenantDisable: "调整租户状态",
    llmServerCreate: "创建模型服务",
    llmServerUpdate: "修改模型服务",
    llmServerDelete: "删除模型服务",
    approvalTaskApprove: "同意审批",
    approvalTaskReject: "拒绝审批",
    openApiApiKeyIssue: "签发 API Key",
    openApiApiKeyRevoke: "撤销 API Key",
    appPublish: "发布托管应用",
    appStop: "停止托管应用",
    appDelete: "删除托管应用",
    appDataExport: "导出应用数据",
    appDataRestore: "恢复应用数据",
    appVisibilityChange: "修改应用可见范围",
    appSecretSet: "设置应用密钥",
  },
  "en-US": {
    tenantMount: "Mount department to tenant",
    tenantUnmount: "Remove department tenant mount",
    tenantDisable: "Change tenant status",
    llmServerCreate: "Create model service",
    llmServerUpdate: "Update model service",
    llmServerDelete: "Delete model service",
    approvalTaskApprove: "Approve request",
    approvalTaskReject: "Reject request",
    openApiApiKeyIssue: "Issue API Key",
    openApiApiKeyRevoke: "Revoke API Key",
    appPublish: "Publish hosted application",
    appStop: "Stop hosted application",
    appDelete: "Delete hosted application",
    appDataExport: "Export application data",
    appDataRestore: "Restore application data",
    appVisibilityChange: "Change application visibility",
    appSecretSet: "Set application secret",
  },
  ja: {
    tenantMount: "部門をテナントにマウント",
    tenantUnmount: "部門のテナントマウントを解除",
    tenantDisable: "テナント状態を変更",
    llmServerCreate: "モデルサービスを作成",
    llmServerUpdate: "モデルサービスを変更",
    llmServerDelete: "モデルサービスを削除",
    approvalTaskApprove: "承認に同意",
    approvalTaskReject: "承認を拒否",
    openApiApiKeyIssue: "API Key を発行",
    openApiApiKeyRevoke: "API Key を取り消し",
    appPublish: "ホスト型アプリを公開",
    appStop: "ホスト型アプリを停止",
    appDelete: "ホスト型アプリを削除",
    appDataExport: "アプリデータをエクスポート",
    appDataRestore: "アプリデータを復元",
    appVisibilityChange: "アプリの公開範囲を変更",
    appSecretSet: "アプリの秘密情報を設定",
  },
};

const ORG_COLUMN: Record<string, string> = {
  "zh-Hans": "组织架构",
  "en-US": "Organization structure",
  ja: "組織構成",
};

const USAGE_TASK: Record<string, string> = {
  "zh-Hans": "深度研究",
  "en-US": "Deep research",
  ja: "詳細リサーチ",
};

describe("sensitive-action and organisation copy", () => {
  it("pins the 17 action captions, the organisation column and the usage-type label", () => {
    for (const [locale, captions] of Object.entries(SENSITIVE_CAPTIONS)) {
      const bs = JSON.parse(readFileSync(resolve(__dirname, `../../public/locales/${locale}/bs.json`), "utf-8"));
      expect(bs.log.eventTypeEnum).toEqual(expect.objectContaining(captions));
      expect(bs.log.org.column).toBe(ORG_COLUMN[locale]);
      expect(bs.log.csvHeaders.org).toBe(ORG_COLUMN[locale]);
      expect(bs.log.runtime.fields.operator_dept_path).toBe(ORG_COLUMN[locale]);
      expect(bs.log.usageType.task).toBe(USAGE_TASK[locale]);
    }
  });
});
