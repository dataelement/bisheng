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

  it("allows Child Admins regardless of web_menu", () => {
    // Backend strips ``model`` from a Child Admin's web_menu, but PRD §6.1
    // (model tenant isolation) lets them manage models in their own tenant.
    // Mirror the backend ``get_tenant_admin_user`` decision.
    expect(
      canManageModelSettings({
        role: "editor",
        web_menu: ["build", "knowledge"],
        is_child_admin: true,
      } as any),
    ).toBe(true);
  });

  it("rejects regular users who happen to share a tenant with a Child Admin", () => {
    expect(
      canManageModelSettings({
        role: "editor",
        web_menu: ["build"],
        is_child_admin: false,
      } as any),
    ).toBe(false);
  });
});
