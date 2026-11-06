/**
 * The route filter must not touch the shared route table.
 *
 * It used to write filtered children back into `privateRouter`, and those copies
 * had already lost their `permission` key — so every build after the first left
 * nested routes unfiltered while top-level ones were still filtered. A user then
 * reached a list page they should not see and hit /404 on its editor route.
 */
import { describe, expect, it } from "vitest"

import { getPrivateRouter, resolveRoutePermissions } from "@/routes"

type RouteNode = { path?: string; children?: RouteNode[] }

const pathsOf = (routes: RouteNode[]): string[] =>
  routes.flatMap((route) => [route.path, ...(route.children ? pathsOf(route.children) : [])]).filter((path): path is string => typeof path === "string")

describe("getPrivateRouter", () => {
  it("keeps the dataset route for gzx01's tenant-admin permissions on 116", () => {
    const permissions = resolveRoutePermissions({
      web_menu: ["admin", "home", "linsight_task_mode", "subscription", "apps", "workstation", "knowledge_space", "knowledge", "build"],
      is_department_admin: false,
      is_child_admin: true,
    })
    const router = getPrivateRouter(permissions)
    expect(pathsOf(router.routes as RouteNode[])).toContain("dataset")
    router.dispose()
  })

  it.each([false, true])("requires a dataset grant for a non-tenant admin (department admin: %s)", (isDepartmentAdmin) => {
    const user = {
      web_menu: ["admin", "system_config"],
      is_department_admin: isDepartmentAdmin,
      is_child_admin: false,
    }
    const deniedRouter = getPrivateRouter(resolveRoutePermissions(user))
    expect(pathsOf(deniedRouter.routes as RouteNode[])).not.toContain("dataset")
    deniedRouter.dispose()

    const grantedRouter = getPrivateRouter(resolveRoutePermissions({
      ...user,
      web_menu: [...user.web_menu, "dataset"],
    }))
    expect(pathsOf(grantedRouter.routes as RouteNode[])).toContain("dataset")
    grantedRouter.dispose()
  })

  it("filters the same way however many times it is called", () => {
    const withBoard = pathsOf(getPrivateRouter(["board"]).routes as RouteNode[])
    expect(withBoard).toContain("dashboard")
    expect(withBoard).toContain("dashboard/:id")

    const withoutBoard = pathsOf(getPrivateRouter([]).routes as RouteNode[])
    expect(withoutBoard).not.toContain("dashboard")
    expect(withoutBoard).not.toContain("dashboard/:id")

    const withBoardAgain = pathsOf(getPrivateRouter(["board"]).routes as RouteNode[])
    expect(withBoardAgain).toEqual(withBoard)
  })

  it("keeps a denied route as a placeholder in menu-approval mode", () => {
    const paths = pathsOf(getPrivateRouter([], { menuApprovalMode: true }).routes as RouteNode[])

    expect(paths).toContain("dashboard")
    expect(paths).toContain("dashboard/:id")
  })
})
