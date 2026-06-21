import { describe, expect, it } from "vitest";

import { canManageModelSettings, canManageWorkbenchConfig } from "@/pages/ModelPage/manage/permissions";

describe("canManageModelSettings", () => {
  it("allows super admins", () => {
    expect(canManageModelSettings({ role: "admin" } as any)).toBe(true);
  });

  it("allows non-admin users with model menu access in single-tenant", () => {
    expect(
      canManageModelSettings({
        role: "editor",
        web_menu: ["build", "model"],
      } as any),
    ).toBe(true);
  });

  it("rejects non-admin model-menu users in multi-tenant (admin-only)", () => {
    // Multi-tenant: the legacy web_menu['model'] fallback no longer applies —
    // only super admin / Child Admin manage models (mirrors get_tenant_admin_user).
    expect(
      canManageModelSettings({ role: "editor", web_menu: ["build", "model"] } as any, true),
    ).toBe(false);
  });

  it("still allows super admin / global super / Child Admin in multi-tenant", () => {
    expect(canManageModelSettings({ role: "admin" } as any, true)).toBe(true);
    expect(canManageModelSettings({ is_global_super: true } as any, true)).toBe(true);
    expect(canManageModelSettings({ is_child_admin: true } as any, true)).toBe(true);
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

describe("canManageWorkbenchConfig", () => {
  it("allows super admins", () => {
    expect(canManageWorkbenchConfig({ role: "admin" } as any)).toBe(true);
  });

  it("allows Child Admins", () => {
    expect(
      canManageWorkbenchConfig({
        role: "editor",
        is_child_admin: true,
        web_menu: ["build", "model", "workstation"],
      } as any),
    ).toBe(true);
  });

  it("rejects regular members even if web_menu contains workstation/model", () => {
    expect(
      canManageWorkbenchConfig({
        role: "editor",
        is_child_admin: false,
        web_menu: ["build", "model", "workstation"],
      } as any),
    ).toBe(false);
  });
});
