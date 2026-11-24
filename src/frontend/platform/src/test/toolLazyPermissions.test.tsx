import { userContext } from "@/contexts/userContext"
import {
  getGrantablePermissionModelsApi,
  getMyResourcePermissionsApi,
  getResourcePermissionContextApi,
  getResourcePermissionGrantsApi,
  mutateResourceGrantsApi,
} from "@/controllers/API/permission"
import { getToolsApi } from "@/controllers/API/tools"
import TabTools from "@/pages/BuildPage/tools"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ReactNode } from "react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/controllers/API/tools", () => ({
  getToolsApi: vi.fn(),
}))

vi.mock("@/controllers/API/permission", () => ({
  getGrantablePermissionModelsApi: vi.fn(),
  getMyResourcePermissionsApi: vi.fn(),
  getResourcePermissionContextApi: vi.fn(),
  getResourcePermissionGrantsApi: vi.fn(),
  mutateResourceGrantsApi: vi.fn(),
}))

vi.mock("@/controllers/API/assistant", () => ({
  refreshMcpApi: vi.fn(),
}))

vi.mock("@/controllers/request", async (importOriginal) => ({
  ...await importOriginal<typeof import('@/controllers/request')>(),
  captureAndAlertRequestErrorHoc: (promise: Promise<unknown>) => promise,
}))

vi.mock("@/components/bs-icons", () => ({
  LoadIcon: () => <span data-testid="load-icon" />,
}))

vi.mock("@/components/bs-icons/loading", () => ({
  LoadingIcon: () => <span data-testid="loading-icon" />,
}))

vi.mock("@/components/bs-icons/setting", () => ({
  SettingIcon: () => <span data-testid="setting-icon" />,
}))

vi.mock("@/components/bs-icons/tool", () => ({
  ToolIcon: () => <span data-testid="tool-icon" />,
}))

vi.mock("@/components/bs-comp/cardComponent", () => ({
  TitleIconBg: ({ children }: { children: ReactNode }) => <span>{children}</span>,
}))

vi.mock("@/components/bs-ui/accordion", () => ({
  Accordion: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AccordionContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AccordionItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AccordionTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))









vi.mock("@/pages/BuildPage/tools/EditTool", async () => {
  const React = await import("react")
  return {
    default: React.forwardRef(() => null),
  }
})

vi.mock("@/pages/BuildPage/tools/EditMcp", async () => {
  const React = await import("react")
  return {
    default: React.forwardRef(() => null),
  }
})

vi.mock("@/pages/BuildPage/tools/ToolSet", async () => {
  const React = await import("react")
  return {
    default: React.forwardRef(() => null),
  }
})

function renderToolPage(userId = 7) {
  return render(
    <MemoryRouter>
      <userContext.Provider value={{
        user: { user_id: userId, role: "user", is_global_super: false },
        setUser: vi.fn(),
        savedComponents: [],
        addSavedComponent: vi.fn(),
        checkComponentsName: vi.fn(),
        delComponent: vi.fn(),
      } as never}
      >
        <TabTools onSelect={vi.fn()} />
      </userContext.Provider>
    </MemoryRouter>,
  )
}

describe("tool list lazy permissions", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getToolsApi).mockImplementation(async (type) => {
      if (type === "custom") {
        return [{
          id: 10,
          name: "API Tool",
          description: "Custom API",
          is_preset: 0,
          children: [],
        }]
      }
      return []
    })
    vi.mocked(getMyResourcePermissionsApi).mockResolvedValue({
      mode: "CUSTOM",
      actions: ["edit"],
      sources: [],
      roster_complete: false,
    })
  })

  it("loads tool actions only after hovering a tool item", async () => {
    renderToolPage()

    fireEvent.click(screen.getByText("tools.customTools"))
    await screen.findByText("API Tool")

    expect(getMyResourcePermissionsApi).not.toHaveBeenCalled()
    expect(screen.queryByLabelText("edit")).toBeNull()

    const row = screen.getByText("API Tool").closest(".group")
    expect(row).not.toBeNull()
    fireEvent.mouseEnter(row as Element)

    await waitFor(() => {
      expect(getMyResourcePermissionsApi).toHaveBeenCalledWith("tool", "10")
      expect(screen.getByLabelText("edit")).toBeInTheDocument()
    })
  })

  it("dismisses the grant dropdown on a blank click inside the tool permission dialog", async () => {
    const viewer = { key: "viewer", name: "Viewer", level: 1 as const, active: true }
    vi.mocked(getMyResourcePermissionsApi).mockResolvedValue({
      mode: "CUSTOM", actions: ["manage_permission"], sources: [], roster_complete: false,
    })
    vi.mocked(getResourcePermissionContextApi).mockResolvedValue({
      mode: "CUSTOM",
      parent_type: null,
      parent_id: null,
      resource_version: 1,
      catalog_release_id: 1,
      projection_state: "READY",
      can_manage_permission: true,
    })
    vi.mocked(getGrantablePermissionModelsApi).mockResolvedValue([
      viewer, { key: "editor", name: "Editor", level: 2, active: true },
    ])
    vi.mocked(getResourcePermissionGrantsApi).mockResolvedValue({
      data: [{
        assignee_id: "42",
        assignee_version: 1,
        subject: { type: "user", id: "7", name: "Member" },
        model: viewer,
        source: { type: "DIRECT", include_children: false },
        scope: "LOCAL",
        inherited_from: null,
        protected: false,
        editable: true,
      }],
      page_size: 50,
      has_more: false,
      next_cursor: null,
    })
    const user = userEvent.setup()
    renderToolPage(8)

    await user.click(screen.getByText("tools.customTools"))
    const toolName = await screen.findByText("API Tool")
    await user.hover(toolName)
    const permissionIcon = await waitFor(() => {
      const icon = toolName.closest(".group")?.querySelector("svg.lucide-shield")
      if (!icon) throw new Error("Tool permission action is not available")
      return icon
    })
    await user.click(permissionIcon)
    const dialog = await screen.findByRole("dialog", { name: "dialog.title - API Tool" })
    const grant = await screen.findByRole("combobox", { name: "grant.model.42" })
    await user.click(grant)
    expect(grant).toHaveAttribute("aria-expanded", "true")

    await user.click(dialog)

    await waitFor(() => expect(grant).toHaveAttribute("aria-expanded", "false"))
    expect(dialog).toBeInTheDocument()
    expect(mutateResourceGrantsApi).not.toHaveBeenCalled()
  })
})
