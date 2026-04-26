import { describe, expect, it, vi } from "vitest"

// routes/index.tsx reads __APP_ENV__.BASE_URL at module load — set the stub
// before the ESM import gets evaluated. vi.hoisted runs before imports.
vi.hoisted(() => {
  ;(globalThis as any).__APP_ENV__ = { BASE_URL: "" }
})

import { resolveRoutePermissions } from "@/routes"

describe("resolveRoutePermissions", () => {
  it("returns the raw web_menu unchanged for plain users", () => {
    const perms = resolveRoutePermissions({
      web_menu: ["build", "knowledge"],
      is_department_admin: false,
      is_child_admin: false,
    })
    expect(perms).toEqual(["build", "knowledge"])
  })

  it("injects create_app for department admins missing it", () => {
    const perms = resolveRoutePermissions({
      web_menu: ["build", "knowledge"],
      is_department_admin: true,
      is_child_admin: false,
    })
    expect(perms).toContain("create_app")
  })

  it("does not duplicate create_app when already present", () => {
    const perms = resolveRoutePermissions({
      web_menu: ["build", "create_app"],
      is_department_admin: true,
    })
    expect(perms.filter((p) => p === "create_app")).toHaveLength(1)
  })

  it("injects sys for Child Admin when web_menu lacks sys/system_config", () => {
    // Backend strips sys/system_config from non-super, non-dept admins. Mirror
    // the sidebar's is_child_admin gate so the /sys route is reachable.
    const perms = resolveRoutePermissions({
      web_menu: ["build", "knowledge"],
      is_child_admin: true,
    })
    expect(perms).toContain("sys")
  })

  it("does not inject sys when the user is not a Child Admin", () => {
    const perms = resolveRoutePermissions({
      web_menu: ["build"],
      is_child_admin: false,
    })
    expect(perms).not.toContain("sys")
  })

  it("does not duplicate sys when already present in web_menu", () => {
    const perms = resolveRoutePermissions({
      web_menu: ["build", "sys"],
      is_child_admin: true,
    })
    expect(perms.filter((p) => p === "sys")).toHaveLength(1)
  })

  it("handles missing web_menu gracefully", () => {
    expect(resolveRoutePermissions({})).toEqual([])
    expect(resolveRoutePermissions({ is_child_admin: true })).toEqual(["sys"])
  })

  it("matches the real /user/info shape for a Child Admin (caiwu on 114)", () => {
    // Backend strips sys/system_config for non-super, non-dept admins. The
    // resolved perms must include sys so getPrivateRouter doesn't drop the
    // /sys route — that drop was the original /404 bug.
    const perms = resolveRoutePermissions({
      web_menu: ["admin", "workstation", "model", "knowledge_space"],
      is_department_admin: false,
      is_child_admin: true,
    })
    expect(perms).toContain("sys")
    expect(perms).not.toContain("create_app")
  })
})
