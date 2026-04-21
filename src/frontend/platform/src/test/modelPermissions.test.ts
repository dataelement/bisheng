import { describe, expect, it } from "vitest";

import { canManageModelSettings } from "@/pages/ModelPage/manage/permissions";

describe("canManageModelSettings", () => {
  it("allows super admins", () => {
    expect(canManageModelSettings({ role: "admin" } as any)).toBe(true);
  });

  it("allows non-admin users with model menu access", () => {
    expect(
      canManageModelSettings({
        role: "editor",
        web_menu: ["build", "model"],
      } as any),
    ).toBe(true);
  });

  it("rejects users without model menu access", () => {
    expect(
      canManageModelSettings({
        role: "editor",
        web_menu: ["build"],
      } as any),
    ).toBe(false);
  });
});
