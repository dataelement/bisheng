import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  getGrantablePermissionModels,
  getMyResourcePermissions,
  getResourcePermissionGrants,
} from "~/api/permission";
import type {
  PermissionGrantAssignee,
  ResourcePermissionContext,
} from "~/api/permission";
import { PermissionListTab } from "./PermissionListTab";

jest.mock("~/api/permission", () => ({
  getGrantablePermissionModels: jest.fn(),
  getMyResourcePermissions: jest.fn(),
  getResourcePermissionGrants: jest.fn(),
  mutateResourceGrants: jest.fn(),
}));

jest.mock("~/hooks", () => ({
  useLocalize: () => (
    key: string,
    options?: Record<string, string | number>,
  ) => {
    if (!options) return key;
    return `${key}:${Object.values(options).join(",")}`;
  },
}));

const mockedGetGrants = getResourcePermissionGrants as jest.MockedFunction<
  typeof getResourcePermissionGrants
>;
const mockedGetSummary = getMyResourcePermissions as jest.MockedFunction<
  typeof getMyResourcePermissions
>;
const mockedGetModels = getGrantablePermissionModels as jest.MockedFunction<
  typeof getGrantablePermissionModels
>;

const context: ResourcePermissionContext = {
  mode: "CUSTOM",
  parent_type: "knowledge_space",
  parent_id: "space-1",
  resource_version: 4,
  catalog_release_id: 11,
  projection_state: "FINALIZED",
  can_manage_permission: true,
};

function assignee(
  id: number,
  source: "DIRECT" | "DEPARTMENT",
  overrides: Partial<PermissionGrantAssignee> = {},
): PermissionGrantAssignee {
  return {
    assignee_id: id,
    assignee_version: 2,
    subject: { type: "user", id: "7", name: "Alice" },
    model: { key: "standard-viewer", name: "Viewer", level: 1, active: true },
    source: { type: source, include_children: source === "DEPARTMENT" },
    scope: "LOCAL",
    inherited_from: null,
    protected: false,
    editable: true,
    ...overrides,
  };
}

describe("F048 Client PermissionListTab", () => {
  beforeEach(() => {
    mockedGetModels.mockResolvedValue([
      { key: "standard-viewer", name: "Viewer", level: 1, active: true },
    ]);
    mockedGetGrants.mockResolvedValue({
      data: [assignee(1, "DIRECT"), assignee(2, "DEPARTMENT")],
      page_size: 2,
      has_more: true,
      next_cursor: "cursor-2",
    });
    mockedGetSummary.mockResolvedValue({
      mode: "CUSTOM",
      actions: ["visible", "use"],
      sources: [{ type: "DIRECT", include_children: false }],
      roster_complete: false,
    });
  });

  it("keeps direct and department sources as separate rows in the legacy list layout", async () => {
    render(
      <PermissionListTab
        resourceType="knowledge_file"
        resourceId="file-1"
        context={context}
        pageSize={2}
      />,
    );

    await waitFor(() =>
      expect(screen.getAllByText("Alice")).toHaveLength(2),
    );
    expect(screen.getByRole("searchbox")).toBeInTheDocument();
    expect(screen.getByText("f048_permission.source.direct")).toBeInTheDocument();
    expect(
      screen.getByText("f048_permission.source.department"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/f048_permission\.source\.include_children/),
    ).toBeInTheDocument();
  });

  it("renders protected and inherited grants as read-only and paginates by cursor", async () => {
    mockedGetGrants
      .mockResolvedValueOnce({
        data: [
          assignee(3, "DIRECT", {
            protected: true,
            editable: false,
            scope: "INHERITED",
            inherited_from: "folder:parent-1",
          }),
        ],
        page_size: 1,
        has_more: true,
        next_cursor: "cursor-2",
      })
      .mockResolvedValueOnce({
        data: [assignee(4, "DIRECT", { subject: { type: "user", id: "8", name: "Bob" } })],
        page_size: 1,
        has_more: false,
        next_cursor: null,
      });

    render(
      <PermissionListTab
        resourceType="knowledge_file"
        resourceId="file-1"
        context={context}
        pageSize={1}
      />,
    );

    const protectedRow = await screen.findByTestId("permission-assignee-3");
    expect(protectedRow).toHaveAttribute("data-editable", "false");
    expect(
      screen.getByLabelText("f048_permission.roster.protected"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "f048_permission.roster.load_more" }));

    expect(await screen.findByText("Bob")).toBeInTheDocument();
    expect(mockedGetGrants).toHaveBeenLastCalledWith(
      "knowledge_file",
      "file-1",
      { cursor: "cursor-2", page_size: 1 },
    );
  });

  it("requests only the caller summary without roster permission", async () => {
    render(
      <PermissionListTab
        resourceType="knowledge_file"
        resourceId="file-1"
        context={{ ...context, can_manage_permission: false }}
      />,
    );

    expect(
      await screen.findByText("f048_permission.roster.summary_only"),
    ).toBeInTheDocument();
    expect(screen.getByText("visible")).toBeInTheDocument();
    expect(mockedGetSummary).toHaveBeenCalledWith(
      "knowledge_file",
      "file-1",
    );
    expect(mockedGetGrants).not.toHaveBeenCalled();
  });
});
