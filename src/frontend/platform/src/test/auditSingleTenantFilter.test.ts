// Single-tenant degradation of the audit-log filter + the audit i18n keys the
// hosted-application (F055) release family needs.
//
// Background: `multi_tenant.enabled` defaults to false on a standard docker
// install, so the tenant-management module and its three `tenant.*` actions are
// a shell: they can never match a row. The flag only reaches the frontend through
// React context, so `controllers/API/log` takes it as an argument.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { getActionsApi, getModulesApi } from "@/controllers/API/log";
import { actionToI18nKey } from "@/pages/LogPage/systemLog";

const LOCALES = ["zh-Hans", "en-US", "ja"] as const;

type BsLocale = {
  log: {
    objectTypeEnum: Record<string, string>;
    systemIdEnum: Record<string, string>;
    eventTypeEnum: Record<string, string>;
  };
};

const readLocale = (locale: string): BsLocale =>
  JSON.parse(readFileSync(resolve(__dirname, `../../public/locales/${locale}/bs.json`), "utf-8")) as BsLocale;

describe("audit filter — single-tenant degradation", () => {
  it("keeps the tenant-management module when multi-tenant is enabled", async () => {
    const { data } = await getModulesApi({ multiTenantEnabled: true });
    expect(data.map((m) => m.value)).toContain("tenant");
  });

  it("defaults to the full list so callers that do not pass the flag are unaffected", async () => {
    const { data } = await getModulesApi();
    expect(data.map((m) => m.value)).toContain("tenant");
  });

  it("drops only the tenant-management module when multi-tenant is disabled", async () => {
    const full = (await getModulesApi({ multiTenantEnabled: true })).data.map((m) => m.value);
    const single = (await getModulesApi({ multiTenantEnabled: false })).data.map((m) => m.value);
    expect(single).not.toContain("tenant");
    expect(single).toEqual(full.filter((value: string) => value !== "tenant"));
  });

  it("drops the tenant.* actions from the global action list when multi-tenant is disabled", async () => {
    const single = await getActionsApi({ multiTenantEnabled: false });
    expect(single.some((a) => a.value.startsWith("tenant."))).toBe(false);
    // Neighbouring v2 namespaces must survive — the filter is prefix-scoped,
    // not "anything containing the word tenant".
    expect(single.some((a) => a.value.startsWith("llm.server."))).toBe(true);
    expect(single.some((a) => a.value.startsWith("app.release."))).toBe(true);
  });

  it("keeps the tenant.* actions when multi-tenant is enabled", async () => {
    const full = await getActionsApi({ multiTenantEnabled: true });
    expect(full.map((a) => a.value)).toEqual(
      expect.arrayContaining(["tenant.mount", "tenant.unmount", "tenant.disable"]),
    );
  });
});

describe("audit i18n — hosted application release family", () => {
  it("localizes the app_version object type in every language", () => {
    for (const locale of LOCALES) {
      const bs = readLocale(locale);
      expect(bs.log.objectTypeEnum.app_version).toBeTruthy();
    }
  });

  it("localizes the raw namespace of every app.* / open_api.* row", () => {
    // `renderSystemId` falls back to `log.systemIdEnum.<first action segment>`
    // for v2 rows, i.e. the on-wire `app` / `open_api`, not the camelCase
    // dropdown keys `appFactory` / `openApi`.
    for (const locale of LOCALES) {
      const bs = readLocale(locale);
      expect(bs.log.systemIdEnum.app).toBeTruthy();
      expect(bs.log.systemIdEnum.open_api).toBeTruthy();
    }
  });

  it("has an eventTypeEnum entry for every app.release.* action", async () => {
    const releaseActions = (await getActionsApi()).filter((a) => a.value.startsWith("app.release."));
    expect(releaseActions.length).toBe(16);
    for (const locale of LOCALES) {
      const bs = readLocale(locale);
      for (const action of releaseActions) {
        expect(bs.log.eventTypeEnum[actionToI18nKey(action.value)]).toBeTruthy();
      }
    }
  });
});
