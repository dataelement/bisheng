import {
  getMyResourcePermissionsApi,
  getResourcePermissionGrantsApi,
  type ResourcePermissionContext,
} from "@/controllers/API/permission"
import { PermissionListTab } from "@/components/bs-comp/permission/PermissionListTab"
import { fireEvent, render, screen, waitFor } from "@/test/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: vi.fn(),
  getResourcePermissionGrantsApi: vi.fn(),
}))

const customContext: ResourcePermissionContext = {
  mode: "CUSTOM",
  parent_type: "knowledge_space",
  parent_id: "space-1",
  resource_version: 7,
  catalog_release_id: 12,
  projection_state: "READY",
  can_manage_permission: true,
}

const directAssignee = {
  assignee_id: 101,
  assignee_version: 3,
  subject: { type: "user" as const, id: "7", name: "Alice" },
  model: {
    key: "editor",
    name: "Editor",
    level: 2 as const,
    active: true,
  },
  source: { type: "DIRECT", include_children: false },
  scope: "LOCAL" as const,
  inherited_from: null,
  protected: true,
  editable: false,
}

const departmentAssignee = {
  assignee_id: 102,
  assignee_version: 4,
  subject: { type: "user" as const, id: "7", name: "Alice" },
  model: {
    key: "manager",
    name: "Manager",
    level: 3 as const,
    active: true,
  },
  source: { type: "DEPARTMENT", include_children: true },
  scope: "LOCAL" as const,
  inherited_from: null,
  protected: false,
  editable: true,
}

describe("F048 PermissionListTab", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getResourcePermissionGrantsApi).mockResolvedValue({
      data: [directAssignee, departmentAssignee],
      page_size: 50,
      has_more: false,
      next_cursor: null,
    })
    vi.mocked(getMyResourcePermissionsApi).mockResolvedValue({
      mode: "CUSTOM",
      actions: ["visible", "edit"],
      sources: [{ type: "DIRECT", include_children: false }],
      roster_complete: false,
    })
  })

  it("keeps direct and department sources as separate roster rows", async () => {
    render(
      <PermissionListTab
        resourceType="knowledge_file"
        resourceId="file-1"
        context={customContext}
      />,
    )

    expect(
      await screen.findByTestId("permission-assignee-101"),
    ).toHaveTextContent("Alice")
    expect(screen.getByTestId("permission-assignee-101")).toHaveTextContent(
      "Editor",
    )
    expect(screen.getByTestId("permission-assignee-101")).toHaveTextContent(
      "source.direct",
    )
    expect(screen.getByTestId("permission-assignee-102")).toHaveTextContent(
      "Manager",
    )
    expect(screen.getByTestId("permission-assignee-102")).toHaveTextContent(
      "source.department",
    )
    expect(screen.getByTestId("permission-assignee-102")).toHaveTextContent(
      "source.includeChildren",
    )
    expect(screen.getAllByText("Alice")).toHaveLength(2)
    expect(screen.getByTestId("permission-assignee-101")).toHaveTextContent(
      "roster.protected",
    )
  })

  it("renders inherited parent and forces inherited rows read-only", async () => {
    vi.mocked(getResourcePermissionGrantsApi).mockResolvedValue({
      data: [
        {
          ...departmentAssignee,
          scope: "INHERITED",
          inherited_from: "knowledge_space:space-1",
          editable: false,
        },
      ],
      page_size: 50,
      has_more: false,
      next_cursor: null,
    })

    render(
      <PermissionListTab
        resourceType="knowledge_file"
        resourceId="file-1"
        context={{ ...customContext, mode: "INHERIT" }}
      />,
    )

    expect(await screen.findByText("mode.inherit")).toBeInTheDocument()
    expect(screen.getAllByText("knowledge_space:space-1")).toHaveLength(2)
    const row = screen.getByTestId("permission-assignee-102")
    expect(row).toHaveTextContent("scope.inherited")
    expect(row).toHaveTextContent("knowledge_space:space-1")
    expect(row).toHaveAttribute("data-editable", "false")
  })

  it("requests only the current-user summary without roster permission", async () => {
    render(
      <PermissionListTab
        resourceType="workflow"
        resourceId="flow-1"
        context={{ ...customContext, can_manage_permission: false }}
      />,
    )

    expect(await screen.findByText("visible")).toBeInTheDocument()
    expect(screen.getByText("edit")).toBeInTheDocument()
    expect(getMyResourcePermissionsApi).toHaveBeenCalledWith(
      "workflow",
      "flow-1",
    )
    expect(getResourcePermissionGrantsApi).not.toHaveBeenCalled()
    expect(screen.getByText("roster.summaryOnly")).toBeInTheDocument()
  })

  it("appends cursor pages without requesting a total", async () => {
    vi.mocked(getResourcePermissionGrantsApi)
      .mockResolvedValueOnce({
        data: [directAssignee],
        page_size: 1,
        has_more: true,
        next_cursor: "opaque-next",
      })
      .mockResolvedValueOnce({
        data: [departmentAssignee],
        page_size: 1,
        has_more: false,
        next_cursor: null,
      })

    render(
      <PermissionListTab
        resourceType="knowledge_file"
        resourceId="file-1"
        context={customContext}
        pageSize={1}
      />,
    )
    fireEvent.click(
      await screen.findByRole("button", { name: "roster.loadMore" }),
    )

    await waitFor(() => {
      expect(screen.getByTestId("permission-assignee-102")).toBeInTheDocument()
    })
    expect(getResourcePermissionGrantsApi).toHaveBeenNthCalledWith(
      2,
      "knowledge_file",
      "file-1",
      { cursor: "opaque-next", page_size: 1 },
    )
  })
})
