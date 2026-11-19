import {
  getGrantablePermissionModelsApi,
  getMyResourcePermissionsApi,
  getResourcePermissionGrantsApi,
  mutateResourceGrantsApi,
  type PermissionGrantAssignee,
  type ResourcePermissionContext,
} from "@/controllers/API/permission"
import { PermissionListTab } from "@/components/bs-comp/permission/PermissionListTab"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { fireEvent, render, screen, waitFor } from "@/test/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/controllers/API/permission", () => ({
  getGrantablePermissionModelsApi: vi.fn(),
  getMyResourcePermissionsApi: vi.fn(),
  getResourcePermissionGrantsApi: vi.fn(),
  mutateResourceGrantsApi: vi.fn(),
}))

vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({ bsConfirm: vi.fn() }))

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
  assignee_id: "101",
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
  assignee_id: "102",
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

describe("F118 pure visibility source roster", () => {
  const pureModel = {
    key: "pure-original",
    name: "Original visible model",
    level: 3 as const,
    active: true,
    visibility_only: true,
  };
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getGrantablePermissionModelsApi).mockResolvedValue([pureModel]);
  });

  it("keeps both sources visible and removes only the confirmed inactive source identity", async () => {
    const retired: PermissionGrantAssignee = {
      ...departmentAssignee,
      assignee_id: "201",
      assignee_version: 6,
      model: { ...pureModel, key: "old-pure", active: false },
      source: { type: "DIRECT", include_children: false },
    };
    const retained: PermissionGrantAssignee = {
      ...departmentAssignee,
      assignee_id: "202",
      model: pureModel,
    };
    vi.mocked(getResourcePermissionGrantsApi).mockResolvedValue({
      data: [retired, retained],
      page_size: 50,
      has_more: false,
      next_cursor: null,
    });
    const response = { resource_version: 8, items: [retained] };
    vi.mocked(mutateResourceGrantsApi).mockResolvedValue(response);
    const changed = vi.fn();
    render(
      <PermissionListTab
        resourceType="tool"
        resourceId="tool-1"
        context={customContext}
        onMutationSuccess={changed}
      />,
    );
    const remove = await screen.findByRole("button", {
      name: "grant.remove.201",
    });
    expect(screen.getByTestId("permission-assignee-202")).toBeInTheDocument();
    fireEvent.click(remove);
    expect(mutateResourceGrantsApi).not.toHaveBeenCalled();
    expect(bsConfirm).toHaveBeenCalledOnce();
    vi.mocked(bsConfirm).mock.calls[0][0].onOk?.(vi.fn());
    await waitFor(() => expect(changed).toHaveBeenCalledWith(response));
    expect(vi.mocked(mutateResourceGrantsApi).mock.calls[0][2]).toMatchObject({
      expected_resource_version: 7,
      expected_catalog_release_id: 12,
      changes: [
        { op: "REMOVE", assignee_id: "201", expected_assignee_version: 6 },
      ],
    });
    expect(screen.queryByTestId("permission-assignee-201")).toBeNull();
    expect(screen.getByTestId("permission-assignee-202")).toHaveTextContent(
      "source.department",
    );
    expect(retained.model.level).toBe(3);
  });

  it("displays only the server self summary when pure visibility has no management right", async () => {
    vi.mocked(getMyResourcePermissionsApi).mockResolvedValue({
      mode: "CUSTOM",
      actions: ["visible", "rename"],
      sources: [{ type: "DIRECT", include_children: false }],
      roster_complete: false,
    });
    render(
      <PermissionListTab
        resourceType="knowledge_file"
        resourceId="file-1"
        context={{ ...customContext, can_manage_permission: false }}
      />,
    );
    expect(await screen.findByText("visible")).toBeInTheDocument();
    expect(screen.getByText("rename")).toBeInTheDocument();
    expect(screen.queryByText("edit")).toBeNull();
    expect(screen.queryByText("use")).toBeNull();
    expect(getResourcePermissionGrantsApi).not.toHaveBeenCalled();
    expect(mutateResourceGrantsApi).not.toHaveBeenCalled();
  });
});

describe("F048 PermissionListTab", () => {
  it("searches the server roster beyond the currently loaded page", async () => {
    vi.mocked(getResourcePermissionGrantsApi).mockResolvedValueOnce({ data: [directAssignee], page_size: 50, has_more: true, next_cursor: "next" })
      .mockResolvedValueOnce({ data: [{ ...directAssignee, assignee_id: "999", subject: { type: "user", id: "99", name: "Later user" } }], page_size: 50, has_more: false, next_cursor: null });
    render(<PermissionListTab resourceType="workflow" resourceId="flow-1" context={customContext} />);
    await screen.findByTestId("permission-assignee-101");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Later" } });
    await screen.findByTestId("permission-assignee-999");
    expect(getResourcePermissionGrantsApi).toHaveBeenLastCalledWith("workflow", "flow-1", { cursor: null, page_size: 50, keyword: "Later", subject_type: "user" });
  });
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getGrantablePermissionModelsApi).mockResolvedValue([
      {
        key: "manager",
        name: "Manager",
        level: 3,
        active: true,
      },
      {
        key: "editor",
        name: "Editor",
        level: 2,
        active: true,
      },
    ])
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
    expect(screen.getByLabelText("roster.protected")).toBeInTheDocument()
  })

  it("shows inherited source and forces inherited rows read-only", async () => {
    vi.mocked(getResourcePermissionGrantsApi).mockResolvedValue({
      data: [
        {
          ...departmentAssignee,
          scope: "INHERITED",
          inherited_from: "folder:94661",
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

    const row = await screen.findByTestId("permission-assignee-102")
    expect(row).toHaveTextContent("scope.inherited")
    expect(row).toHaveTextContent("roster.parentFolder")
    expect(row).not.toHaveTextContent("folder:94661")
    expect(row).toHaveAttribute("data-editable", "false")
  })

  it("shows the resolved inherited resource name when available", async () => {
    vi.mocked(getResourcePermissionGrantsApi).mockResolvedValue({
      data: [
        {
          ...departmentAssignee,
          scope: "INHERITED",
          inherited_from: "folder:94661",
          inherited_from_name: "Release Notes",
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

    const row = await screen.findByTestId("permission-assignee-102")
    expect(row).toHaveTextContent("Release Notes")
    expect(row).not.toHaveTextContent("folder:94661")
  })

  it("keeps assignees outside the current user's grantable models read-only", async () => {
    vi.mocked(getGrantablePermissionModelsApi).mockResolvedValue([
      {
        key: "editor",
        name: "Editor",
        level: 2,
        active: true,
      },
    ])
    vi.mocked(getResourcePermissionGrantsApi).mockResolvedValue({
      data: [
        {
          ...departmentAssignee,
          model: {
            key: "owner",
            name: "Owner",
            level: 4,
            active: true,
          },
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
        context={customContext}
      />,
    )

    const ownerRow = await screen.findByTestId("permission-assignee-102")
    await waitFor(() => {
      expect(ownerRow).toHaveAttribute("data-editable", "false")
    })
    expect(screen.queryByLabelText("grant.model.102")).toBeNull()
    expect(screen.queryByLabelText("grant.remove.102")).toBeNull()
    expect(ownerRow).toHaveTextContent("Owner")
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
      { cursor: "opaque-next", page_size: 1, keyword: "", subject_type: "user" },
    )
  })
})
