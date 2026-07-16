import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import { userContext } from "@/contexts/userContext"
import HeaderMenu from "@/layout/HeaderMenu"

vi.hoisted(() => {
  ;(globalThis as any).__APP_ENV__ = { BASE_URL: "" }
})

vi.mock("@/components/bs-icons", () => ({
  TabIcon: () => <span aria-hidden="true" />,
}))

describe("HeaderMenu for Child Admin", () => {
  it("shows application, tool, and workbench tabs without role web_menu grants", () => {
    const user = {
      user_id: 1,
      user_name: "child-admin",
      role: "user",
      web_menu: [],
      is_child_admin: true,
    }

    render(
      <MemoryRouter initialEntries={["/build/apps"]}>
        <userContext.Provider value={{ user } as any}>
          <HeaderMenu />
        </userContext.Provider>
      </MemoryRouter>,
    )

    expect(screen.getByText("build.app")).toBeInTheDocument()
    expect(screen.getByText("build.tools")).toBeInTheDocument()
    expect(screen.getByText("build.workbench")).toBeInTheDocument()
  })
})
