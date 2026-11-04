/**
 * F056 T031 — GOV-07: the hosted-application feature adds no permission point
 * and no menu entry (AC-35, AC-36, AC-37, AC-38).
 *
 * This is a verification task with nothing to build, which is exactly the kind
 * that gets "verified" by looking at a screenshot once. The claims are all
 * negative — *no* new id, *no* new route permission, *no* change to the new-role
 * defaults — and a negative claim only stays true if something counts.
 *
 * So each acceptance criterion is turned into an inventory with an exact
 * expected value. Adding a hosted-application permission point would be a
 * perfectly reasonable-looking change; it fails here, which is the point.
 */
import {
  ADMIN_CHILD_MENUS,
  ADMIN_PARENT_ID,
  CHILD_DEPENDENTS,
  DEFAULT_ENABLED_MENU_IDS,
  TASK_MODE_MENU_ID,
  WORKBENCH_CHILD_MENUS,
  WORKBENCH_PARENT_ID,
  normalizeRoleMenuSelection,
} from "@/pages/SystemPage/components/roleMenuSelection"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it } from "vitest"

function source(relativePath: string): string {
  return readFileSync(resolve(__dirname, "..", relativePath), "utf-8")
}

describe("AC-37 — the role config screen's inventory is unchanged", () => {
  it("still offers the same two parents and the same children", () => {
    // Frozen deliberately as literals rather than as a count: a swap (one entry
    // removed, one added) keeps a count honest and changes the screen.
    expect([WORKBENCH_PARENT_ID, ADMIN_PARENT_ID]).toEqual(["workstation", "admin"])
    expect([...WORKBENCH_CHILD_MENUS]).toEqual([
      "home",
      "apps",
      "subscription",
      "knowledge_space",
    ])
    expect(TASK_MODE_MENU_ID).toBe("linsight_task_mode")
    expect([...ADMIN_CHILD_MENUS]).toEqual([
      "board",
      "model",
      "log",
      "knowledge",
      "create_knowledge",
      "build",
      "create_app",
      "evaluation",
      "dataset",
      "mark_task",
    ])
  })

  it("counts 17 selectable entries, none of them about hosted applications", () => {
    const all = [
      WORKBENCH_PARENT_ID,
      ADMIN_PARENT_ID,
      ...WORKBENCH_CHILD_MENUS,
      TASK_MODE_MENU_ID,
      ...ADMIN_CHILD_MENUS,
    ]
    expect(all).toHaveLength(17)
    expect(new Set(all).size).toBe(17)
    expect(all.filter((id) => /app_runtime|hosted|deploy|publish|square/i.test(id))).toEqual([])
  })

  it("keeps the two nesting rules the editor cascades on", () => {
    expect(CHILD_DEPENDENTS).toEqual({
      home: [TASK_MODE_MENU_ID],
      build: ["create_app"],
      knowledge: ["create_knowledge"],
    })
  })

  it("leaves a new role on 'build on, create-app off'", () => {
    // The half that matters for AC-35: a fresh role can reach the build page
    // and still cannot create an application. Turning `create_app` on by
    // default would silently hand the new entry to every role created after the
    // upgrade.
    expect([...DEFAULT_ENABLED_MENU_IDS]).toContain("build")
    expect([...DEFAULT_ENABLED_MENU_IDS]).not.toContain("create_app")
    expect([...DEFAULT_ENABLED_MENU_IDS]).toEqual([
      "workstation",
      "home",
      "linsight_task_mode",
      "apps",
      "subscription",
      "knowledge_space",
      "admin",
      "knowledge",
      "build",
    ])
  })

  it("still cascades create_app off when build is switched off", () => {
    expect(
      normalizeRoleMenuSelection(["admin", "create_app"]).sort(),
    ).toEqual(["admin"])
    expect(
      normalizeRoleMenuSelection(["admin", "build", "create_app"]).sort(),
    ).toEqual(["admin", "build", "create_app"])
  })
})

describe("AC-35 / AC-36 — the build page's create entry, and everything that is not it", () => {
  const appsPage = source("pages/BuildPage/apps.tsx")

  it("gates the create entry on create_app and on nothing new", () => {
    expect(appsPage).toContain("includes('create_app')")
    // No second gate was introduced for hosted applications: the only reason a
    // create entry can be hidden is still the role menu permission.
    expect(appsPage).not.toMatch(/includes\('create_(hosted_)?app_runtime'\)/)
  })

  it("does not offer a hosted-application create entry at all this version", () => {
    // AC-35: the only way a hosted application enters the build list is the
    // CLI first import. A template / new-app entry pointing at the hosted type
    // would be the regression.
    expect(appsPage).toContain("AppType.HOSTED_APP")
    expect(appsPage).toMatch(
      /tempTypeRef\.current !== AppType\.HOSTED_APP \? tempTypeRef\.current : AppType\.FLOW/,
    )
  })

  it("drives the per-card management entries off resource actions, not off create_app", () => {
    // AC-36: someone with `build` but no `create_app` keeps run / access /
    // iterate / detail-page management. Those are per-resource ReBAC actions,
    // so the create-app switch cannot reach them.
    for (const action of ["'manage_permission'", "'delete'", "'unpublish'", "'publish'", "'edit'"]) {
      expect(appsPage).toContain(`hasResourceAction(resourceActions, id, ${action})`)
    }
    expect(appsPage).not.toMatch(/canCreateApp\s*&&\s*can(Manage|Delete|Publish)/)
  })
})

describe("AC-38 — three bearing surfaces, all of them existing pages", () => {
  const routes = source("routes/index.tsx")

  it("routes the hosted-application pages under the existing build permission", () => {
    expect(routes).toContain(
      `{ path: "build/apps/:appId", element: <HostedAppDetail />, permission: 'build', }`,
    )
    expect(routes).toContain(`{ path: "build/apps", element: <Apps />, permission: 'build', }`)
  })

  it("introduces no route permission id outside the frozen set", () => {
    const declared = new Set(
      Array.from(routes.matchAll(/permission:\s*["']([a-z_]+)["']/g)).map((m) => m[1]),
    )
    expect([...declared].sort()).toEqual([
      "board",
      "build",
      "create_app",
      "dataset",
      "evaluation",
      "knowledge",
      "log",
      "mark_task",
      "model",
      "sys",
      "workstation",
    ])
  })

  it("adds no top-level menu for the app factory", () => {
    // The governance surface is the tenant-admin view of the *same* build page
    // and the usage surface is the client square — neither is a menu of its own.
    const header = source("layout/HeaderMenu.tsx")
    expect(header).not.toMatch(/app_runtime|hostedApp|应用工场/)
  })
})
