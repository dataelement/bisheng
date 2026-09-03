import { userContext } from "@/contexts/userContext"
import { getMyResourcePermissionsApi } from "@/controllers/API/permission"
import { getToolsApi } from "@/controllers/API/tools"
import TabTools from "@/pages/BuildPage/tools"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/controllers/API/tools", () => ({
  getToolsApi: vi.fn(),
}))

vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: vi.fn(),
}))

vi.mock("@/controllers/API/assistant", () => ({
  refreshMcpApi: vi.fn(),
}))

vi.mock("@/controllers/request", () => ({
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

vi.mock("@/components/bs-ui/button", () => ({
  Button: ({ children, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button type="button" {...props}>{children}</button>
  ),
}))

vi.mock("@/components/bs-ui/input", () => ({
  SearchInput: (props: InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
}))

vi.mock("@/components/bs-ui/badge", () => ({
  Badge: ({ children }: { children: ReactNode }) => <span>{children}</span>,
}))

vi.mock("@/components/bs-ui/tooltip", () => ({
  Tooltip: ({ children }: { children: ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  TooltipProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

vi.mock("@/components/bs-comp/permission/PermissionDialog", () => ({
  PermissionDialog: () => <div data-testid="permission-dialog" />,
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

function renderToolPage() {
  return render(
    <MemoryRouter>
      <userContext.Provider value={{
        user: { user_id: 7, role: "user", is_global_super: false },
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
    expect(screen.queryByTestId("setting-icon")).toBeNull()

    const row = screen.getByText("API Tool").closest(".group")
    expect(row).not.toBeNull()
    fireEvent.mouseEnter(row as Element)

    await waitFor(() => {
      expect(getMyResourcePermissionsApi).toHaveBeenCalledWith("tool", "10")
      expect(screen.getByTestId("setting-icon")).toBeInTheDocument()
    })
  })
})
