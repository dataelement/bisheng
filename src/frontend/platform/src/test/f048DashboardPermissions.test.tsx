import { locationContext } from "@/contexts/locationContext"
import { userContext } from "@/contexts/userContext"
import { getMyResourcePermissionsApi } from "@/controllers/API/permission"
import { DashboardDetail } from "@/pages/Dashboard/components/dashboard/DashboardDetail"
import {
  useDashboardPermissions,
  type DashboardPermissionMap,
} from "@/pages/Dashboard/hook"
import { DashboardListItem } from "@/pages/Dashboard/components/dashboard/DashboardListItem"
import type { Dashboard } from "@/pages/Dashboard/types/dataConfig"
import { fireEvent, render, screen, waitFor } from "@/test/test-utils"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: vi.fn(),
}))

// `DashboardListItem` no longer takes its capabilities as props: it resolves
// them itself through `useLazyDashboardPermission`, which fires only when the
// user reaches for the menu (F027 — the list must not spend one request per
// row). Driving the row therefore means controlling the hook, not the props.
// `useDashboardPermissions` stays real; the Probe below asserts on it.
const lazyPermission = vi.hoisted(() => ({
  current: {
    actions: [] as string[],
    loaded: true,
    loading: false,
    privileged: false,
    ensureLoaded: () => {},
  },
}))

vi.mock("@/pages/Dashboard/hook", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/pages/Dashboard/hook")>()
  return {
    ...actual,
    useLazyDashboardPermission: () => lazyPermission.current,
  }
})

vi.mock("@/pages/Dashboard/components/editor/EditorCanvas", () => ({
  EditorCanvas: () => <div>dashboard canvas</div>,
}))

vi.mock("@/components/bs-ui/tooltip/tip", () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

vi.mock("@/components/bs-ui/dropdownMenu", () => ({
  DropdownMenu: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
  DropdownMenuContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuItem: ({
    children,
    className,
    disabled,
    onClick,
  }: {
    children: ReactNode
    className?: string
    disabled?: boolean
    onClick?: () => void
  }) => (
    <button
      type="button"
      className={className}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  ),
}))

const dashboard = {
  id: "dashboard-1",
  title: "Operations",
  description: "",
  status: "draft",
  dashboard_type: "custom",
  layout_config: { layouts: [] },
  style_config: { theme: "light" },
  create_time: "2026-07-29T10:00:00Z",
  update_time: "2026-07-29T10:00:00Z",
  is_default: false,
  user_name: "Alice",
  write: false,
  components: [],
} as Dashboard

function renderItem(permissionActions: string[], { privileged = false } = {}) {
  lazyPermission.current = {
    actions: permissionActions,
    loaded: true,
    loading: false,
    privileged,
    ensureLoaded: () => {},
  }
  const callbacks = {
    onSelect: vi.fn(),
    onRename: vi.fn(),
    onDuplicate: vi.fn(),
    onDefault: vi.fn(),
    onShare: vi.fn(),
    onDelete: vi.fn(),
    onPermission: vi.fn(),
  }
  render(
    <locationContext.Provider
      value={{ appConfig: { isDashboardPro: true } } as never}
    >
      <DashboardListItem
        dashboard={dashboard}
        selected={false}
        {...callbacks}
      />
    </locationContext.Provider>,
  )
  return callbacks
}

function Probe({ ids }: { ids: string[] }) {
  const result = useDashboardPermissions(ids)
  const permissions: DashboardPermissionMap = result.permissions
  return (
    <div>
      <span>{result.loading ? "loading" : "ready"}</span>
      <span data-testid="privileged">{result.privileged ? "yes" : "no"}</span>
      <span data-testid="dashboard-1-actions">
        {(permissions["dashboard-1"] ?? []).join(",")}
      </span>
    </div>
  )
}

function PermissionProbe({ ids, admin = false }: { ids: string[]; admin?: boolean }) {
  return (
    <userContext.Provider
      value={{ user: { user_id: 7, role: admin ? "admin" : "user" } } as never}
    >
      <Probe ids={ids} />
    </userContext.Provider>
  )
}

describe("F048 dashboard permission UI", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getMyResourcePermissionsApi).mockResolvedValue({
      mode: "CUSTOM",
      actions: ["edit"],
      sources: [{ type: "DIRECT", include_children: false }],
      roster_complete: false,
    })
  })

  // The row used to take a `visible` prop and refuse to render without it. That
  // gate moved up: the sidebar's list request now returns visible dashboards
  // only, so a row that reaches this component is by construction one the user
  // may see, and the row's own job is narrowed to the mutating actions below.

  it("keeps share, default, and copy behind visibility without implying edit", () => {
    // Visible with no granted action at all — the case an action list can never
    // express, and the one that used to hide every dashboard.
    const callbacks = renderItem([])

    expect(screen.getByText("share")).toBeInTheDocument()
    expect(screen.getByText("setAsDefault")).toBeInTheDocument()
    expect(screen.getByText("duplicate")).toBeInTheDocument()
    expect(screen.queryByText("rename")).toBeNull()
    expect(screen.queryByText("delete")).toBeNull()
    expect(screen.queryByText("managePermission")).toBeNull()

    fireEvent.click(screen.getByText("share"))
    expect(callbacks.onShare).toHaveBeenCalledWith("dashboard-1")
  })

  it("uses distinct edit, delete, and manage_permission actions", () => {
    renderItem(["edit", "delete", "manage_permission"])

    expect(screen.getByText("rename")).toBeInTheDocument()
    expect(screen.getByText("delete")).toBeInTheDocument()
    expect(screen.getByText("managePermission")).toBeInTheDocument()
  })

  it("uses visible for details and edit only for mutations", async () => {
    vi.mocked(getMyResourcePermissionsApi).mockResolvedValue({
      mode: "CUSTOM",
      actions: [],
      sources: [],
      roster_complete: false,
    })

    render(
      <locationContext.Provider
        value={{ appConfig: { isDashboardPro: true } } as never}
      >
        <DashboardDetail
          dashboard={dashboard}
          isLoading={false}
          isCollapsed={false}
          setIsCollapsed={vi.fn()}
          onRename={vi.fn()}
          onShare={vi.fn()}
          onDefault={vi.fn()}
          onEdit={vi.fn()}
        />
      </locationContext.Provider>,
    )

    await waitFor(() =>
      expect(screen.getByText("dashboard canvas")).toBeInTheDocument(),
    )
    expect(screen.getByText("share")).toBeInTheDocument()
    expect(screen.queryByText("publish")).toBeNull()
    expect(screen.queryByText("editDashboard")).toBeNull()
  })

  it("opens every control for an admin, who holds no grants to read", () => {
    // The server waves admins through on identity alone, so their action list
    // comes back empty — reading capability off it hid the whole board.
    renderItem([], { privileged: true })

    expect(screen.getByText("share")).toBeInTheDocument()
    expect(screen.getByText("rename")).toBeInTheDocument()
    expect(screen.getByText("delete")).toBeInTheDocument()
    expect(screen.getByText("managePermission")).toBeInTheDocument()
  })

  it("does not retain dashboard.write as an editor authorization source", () => {
    const files = [
      "src/pages/Dashboard/editor.tsx",
      "src/pages/Dashboard/components/dashboard/DashboardDetail.tsx",
      "src/pages/Dashboard/components/dashboard/DashboardListItem.tsx",
      "src/pages/Dashboard/components/editor/ComponentWrapper.tsx",
      "src/pages/Dashboard/components/editor/EditorCanvas.tsx",
    ]

    for (const file of files) {
      const source = readFileSync(resolve(process.cwd(), file), "utf8")
      expect(source).not.toContain("dashboard.write")
      expect(source).not.toMatch(/\bd\.write\b/)
    }

    const editorSource = readFileSync(
      resolve(
        process.cwd(),
        "src/pages/Dashboard/components/editor/EditorCanvas.tsx",
      ),
      "utf8",
    )
    expect(editorSource).toContain('includes("edit")')
  })

  it("loads each dashboard's concrete action set and fails closed on errors", async () => {
    vi.mocked(getMyResourcePermissionsApi)
      .mockResolvedValueOnce({
        mode: "CUSTOM",
        actions: ["edit"],
        sources: [],
        roster_complete: false,
      })
      .mockRejectedValueOnce(new Error("unavailable"))

    render(<PermissionProbe ids={["dashboard-1", "dashboard-2"]} />)

    await waitFor(() => expect(screen.getByText("ready")).toBeInTheDocument())
    expect(screen.getByTestId("dashboard-1-actions")).toHaveTextContent("edit")
    expect(getMyResourcePermissionsApi).toHaveBeenNthCalledWith(
      1,
      "dashboard",
      "dashboard-1",
    )
    expect(getMyResourcePermissionsApi).toHaveBeenNthCalledWith(
      2,
      "dashboard",
      "dashboard-2",
    )
  })

  it("asks the server for nothing when the user is an admin", async () => {
    render(<PermissionProbe ids={["dashboard-1", "dashboard-2"]} admin />)

    await waitFor(() => expect(screen.getByText("ready")).toBeInTheDocument())
    expect(screen.getByTestId("privileged")).toHaveTextContent("yes")
    // One request per dashboard is the whole cost model here; an admin needs none.
    expect(getMyResourcePermissionsApi).not.toHaveBeenCalled()
  })

  it("deduplicates concurrent action summaries for the same dashboard", async () => {
    render(
      <>
        <PermissionProbe ids={["dashboard-concurrent"]} />
        <PermissionProbe ids={["dashboard-concurrent"]} />
      </>,
    )

    await waitFor(() =>
      expect(
        screen.getAllByText("ready"),
      ).toHaveLength(2),
    )
    expect(getMyResourcePermissionsApi).toHaveBeenCalledTimes(1)
    expect(getMyResourcePermissionsApi).toHaveBeenCalledWith(
      "dashboard",
      "dashboard-concurrent",
    )
  })
})
