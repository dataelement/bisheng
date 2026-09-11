/**
 * The route filter must not touch the shared route table.
 *
 * It used to write filtered children back into `privateRouter`, and those copies
 * had already lost their `permission` key — so every build after the first left
 * nested routes unfiltered while top-level ones were still filtered. A user then
 * reached a list page they should not see and hit /404 on its editor route.
 */
import { describe, expect, it } from "vitest"

import { getPrivateRouter } from "@/routes"

type RouteNode = { path?: string; children?: RouteNode[] }

const pathsOf = (routes: RouteNode[]): string[] =>
  routes.flatMap((route) => [route.path, ...(route.children ? pathsOf(route.children) : [])]).filter(Boolean)

describe("getPrivateRouter", () => {
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
