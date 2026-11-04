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
