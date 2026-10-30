import userEvent from "@testing-library/user-event"
import { render, screen } from "@testing-library/react"
import { MemoryRouter, useLocation } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import { userContext } from "@/contexts/userContext"
import { HeaderMenu } from "@/layout/HeaderMenu"

vi.hoisted(() => {
  Object.defineProperty(globalThis, "__APP_ENV__", {
    configurable: true,
    value: { BASE_URL: "" },
  })
})

vi.mock("@/components/bs-icons", () => ({
  TabIcon: () => <span aria-hidden="true" />,
}))

vi.mock("@/hooks/useDshBrowserConfig", () => ({
  useDshBrowserConfig: () => ({
    config: {
      management_enabled: true,
      enabled: true,
      download_url: null,
      launch_url: "dsh-desktop://login",
    },
    failed: false,
  }),
}))

describe("HeaderMenu for Child Admin", () => {
  const contextValue = (user: Record<string, unknown>) => ({
    user,
    setUser: vi.fn(),
    savedComponents: [],
    addSavedComponent: vi.fn(),
    checkComponentsName: vi.fn(),
    delComponent: vi.fn(),
  })

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
        <userContext.Provider value={contextValue(user)}>
          <HeaderMenu />
        </userContext.Provider>
      </MemoryRouter>,
    )

    expect(screen.getByText("build.app")).toBeInTheDocument()
    expect(screen.getByText("build.tools")).toBeInTheDocument()
    expect(screen.getByText("build.workbench")).toBeInTheDocument()
    expect(screen.queryByText("build.dsh")).toBeNull()
  })

  it("navigates with labeled icon segments and synchronizes selection", async () => {
    function CurrentPath() {
      return <output>{useLocation().pathname}</output>
    }
    const user = userEvent.setup()
    const { container } = render(
      <MemoryRouter initialEntries={["/build/apps"]}>
        <userContext.Provider value={contextValue({ role: "admin", web_menu: [] })}>
          <HeaderMenu />
          <CurrentPath />
        </userContext.Provider>
      </MemoryRouter>,
    )
    expect(screen.getByRole("radio", { name: "build.app" })).toBeChecked()
    const icons = container.querySelectorAll("svg")
    expect(icons).toHaveLength(3)
    icons.forEach(icon => expect(icon).toHaveAttribute("aria-hidden", "true"))
    await user.click(screen.getByRole("radio", { name: "build.tools" }))
    expect(screen.getByText("/build/tools")).toBeInTheDocument()
    expect(screen.getByRole("radio", { name: "build.tools" })).toBeChecked()
    await user.click(screen.getByRole("radio", { name: "build.workbench" }))
    expect(screen.getByText("/build/client")).toBeInTheDocument()
  })

  it("keeps the global header empty on the DSH management page", () => {
    const user = {
      user_id: 1,
      user_name: "child-admin",
      role: "user",
      web_menu: [],
      is_child_admin: true,
    }

    render(
      <MemoryRouter initialEntries={["/dsh?tab=usage"]}>
        <userContext.Provider value={contextValue(user)}>
          <HeaderMenu />
        </userContext.Provider>
      </MemoryRouter>,
    )

    expect(screen.queryByRole("navigation", { name: "dsh.title" })).toBeNull()
  })
})
