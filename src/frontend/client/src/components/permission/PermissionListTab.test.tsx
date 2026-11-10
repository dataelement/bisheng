import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  getGrantablePermissionModels,
  getMyResourcePermissions,
  getResourcePermissionGrants,
  mutateResourceGrants,
} from "~/api/permission";
import type {
  GrantablePermissionModel,
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
    const labels = jest.requireActual("~/locales/en/translation.json").com_permission;
    if (key.startsWith("com_permission.level_")) return labels[key.split(".")[1]];
    if (!options) return key;
    return `${key}:${Object.values(options).join(",")}`;
  },
}));

jest.mock("~/Providers", () => ({
  useConfirm: () => jest.fn().mockResolvedValue(true),
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
const mockedMutate = mutateResourceGrants as jest.MockedFunction<typeof mutateResourceGrants>;
const pureModel: GrantablePermissionModel = {
  key: "pure-visible", name: "Pure visibility", level: 3, active: true, visibility_only: true,
};

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
  id: string,
  source: "DIRECT" | "DEPARTMENT",
  overrides: Partial<PermissionGrantAssignee> = {},
): PermissionGrantAssignee {
  return {
    assignee_id: id,
    assignee_version: 2,
    subject: { type: "user", id: "7", name: "Alice" },
    model: pureModel,
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
    mockedGetModels.mockResolvedValue([pureModel]);
    mockedGetGrants.mockResolvedValue({
      data: [assignee("1", "DIRECT"), assignee("2", "DEPARTMENT")],
      page_size: 2,
      has_more: true,
      next_cursor: "cursor-2",
    });
    mockedGetSummary.mockResolvedValue({
      mode: "CUSTOM",
      actions: ["visible"],
      sources: [{ type: "DIRECT", include_children: false }],
      roster_complete: false,
    });
  });

  it.each([
    ["user", "com_permission.empty_search"],
    ["department", "com_permission.empty_search_departments"],
    ["user_group", "com_permission.empty_search_user_groups"],
  ] as const)("identifies an empty %s search in the authorized list", async (subjectType, message) => {
    mockedGetGrants.mockResolvedValueOnce({
      data: [], page_size: 50, has_more: false, next_cursor: null,
    });
    render(
      <PermissionListTab
        resourceType="knowledge_space"
        resourceId="space-1"
        context={context}
        fixedSubjectType={subjectType}
      />,
    );
    expect(await screen.findByText("com_permission.list_empty_for_subject")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "missing" } });
    expect(await screen.findByText(message)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "" } });
    expect(await screen.findByText("com_permission.list_empty_for_subject")).toBeInTheDocument();
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
    const departmentRow = screen.getByTestId("permission-assignee-2");
    expect(departmentRow).toHaveTextContent("f048_permission.source.department");
    expect(departmentRow).toHaveTextContent("f048_permission.source.include_children");
    await waitFor(() => expect(departmentRow).toHaveAttribute("data-editable", "true"));
    expect(screen.getByLabelText("grant.model.1")).toHaveValue("pure-visible");
    expect(screen.getByLabelText("grant.model.2")).toHaveValue("pure-visible");
    expect(pureModel.level).toBe(3);
  });

  it("removes only the selected pure-visible source with its exact version", async () => {
    const remaining = assignee("2", "DEPARTMENT");
    const onRosterChange = jest.fn();
    mockedMutate.mockResolvedValueOnce({ resource_version: 5, items: [remaining] });
    render(<PermissionListTab resourceType="knowledge_file" resourceId="file-1"
      context={context} onRosterChange={onRosterChange} />);
    const direct = await screen.findByTestId("permission-assignee-1");
    await waitFor(() => expect(direct).toHaveAttribute("data-editable", "true"));
    fireEvent.click(screen.getByLabelText("f048_permission.grant.remove.1"));
    await waitFor(() => expect(mockedMutate).toHaveBeenCalledTimes(1));
    expect(mockedMutate).toHaveBeenCalledWith("knowledge_file", "file-1", {
      idempotency_key: expect.any(String), expected_resource_version: 4, expected_catalog_release_id: 11,
      changes: [{ op: "REMOVE", assignee_id: "1", expected_assignee_version: 2 }],
    });
    await waitFor(() => expect(screen.queryByTestId("permission-assignee-1")).not.toBeInTheDocument());
    expect(screen.getByTestId("permission-assignee-2")).toHaveTextContent("f048_permission.source.department");
    expect(onRosterChange).toHaveBeenLastCalledWith([remaining]);
    expect(JSON.stringify(mockedMutate.mock.calls[0][2])).not.toMatch(/"visibility_only"|"level"|"actions"|"use"/);
  });

  it("keeps an inactive pure-visible source revocable when the server permits it", async () => {
    mockedGetGrants.mockResolvedValueOnce({
      data: [assignee("retired", "DIRECT", {
        assignee_version: 9,
        model: { ...pureModel, key: "retired-pure", name: "Retired visibility", active: false },
      })], page_size: 50, has_more: false, next_cursor: null,
    });
    mockedMutate.mockResolvedValueOnce({ resource_version: 5, items: [] });
    render(<PermissionListTab resourceType="knowledge_file" resourceId="file-1" context={context} />);
    const retired = await screen.findByTestId("permission-assignee-retired");
    expect(retired).toHaveAttribute("data-editable", "true");
    expect(retired).toHaveTextContent("f048_permission.roster.inactive_existing_grant");
    expect(screen.getByLabelText("grant.model.retired")).toHaveValue("retired-pure");
    fireEvent.click(screen.getByLabelText("f048_permission.grant.remove.retired"));
    await waitFor(() => expect(mockedMutate).toHaveBeenCalledTimes(1));
    expect(mockedMutate.mock.calls[0][2].changes).toEqual([
      { op: "REMOVE", assignee_id: "retired", expected_assignee_version: 9 },
    ]);
  });

  it.each([
    { protected: true },
    { editable: false },
    { scope: "INHERITED" as const },
    { model: { ...pureModel, key: "not-grantable" } },
  ])("does not let visibility_only bypass row eligibility: %j", async (overrides) => {
    mockedGetGrants.mockResolvedValueOnce({
      data: [assignee("locked", "DIRECT", overrides), assignee("eligible", "DIRECT")],
      page_size: 50, has_more: false, next_cursor: null,
    });
    render(<PermissionListTab resourceType="knowledge_file" resourceId="file-1" context={context} />);
    const row = await screen.findByTestId("permission-assignee-locked");
    await waitFor(() => expect(screen.getByTestId("permission-assignee-eligible"))
      .toHaveAttribute("data-editable", "true"));
    expect(row).toHaveAttribute("data-editable", "false");
    expect(screen.queryByLabelText("f048_permission.grant.remove.locked")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("grant.model.locked")).not.toBeInTheDocument();
    expect(mockedMutate).not.toHaveBeenCalled();
  });

  it("does not mutate local pure-visible sources while the resource inherits permissions", async () => {
    render(<PermissionListTab resourceType="knowledge_file" resourceId="file-1"
      context={{ ...context, mode: "INHERIT" }} />);
    const row = await screen.findByTestId("permission-assignee-1");
    expect(row).toHaveAttribute("data-editable", "false");
    expect(screen.queryByLabelText("f048_permission.grant.remove.1")).not.toBeInTheDocument();
    expect(mockedGetModels).not.toHaveBeenCalled();
    expect(mockedMutate).not.toHaveBeenCalled();
  });

  it("displays and searches the localized standard role from the server key", async () => {
    mockedGetGrants.mockResolvedValueOnce({
      data: [assignee("owner-locale", "DIRECT", {
        model: {
          key: "owner",
          name: jest.requireActual("~/locales/zh-Hans/translation.json").com_permission.level_owner,
          level: 4,
          active: true,
        },
        protected: true,
        editable: false,
      })],
      page_size: 50,
      has_more: false,
      next_cursor: null,
    });
    render(<PermissionListTab resourceType="knowledge_space" resourceId="space-1" context={context} />);
    expect(await screen.findByText("Owner")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Owner" } });
    expect(screen.getByTestId("permission-assignee-owner-locale")).toHaveTextContent("Owner");
  });

  it("keeps an owner row read-only when owner is not grantable", async () => {
    mockedGetGrants.mockResolvedValueOnce({
      data: [
        assignee("9", "DIRECT", {
          subject: { type: "user", id: "8", name: "Bob" },
          model: { key: "standard-owner", name: "Owner", level: 4, active: true },
        }),
        assignee("10", "DIRECT", {
          subject: { type: "user", id: "10", name: "Carol" },
        }),
      ],
      page_size: 50,
      has_more: false,
      next_cursor: null,
    });

    render(
      <PermissionListTab
        resourceType="knowledge_space"
        resourceId="space-1"
        context={context}
      />,
    );

    const ownerRow = await screen.findByTestId("permission-assignee-9");
    const viewerRow = await screen.findByTestId("permission-assignee-10");
    await waitFor(() => {
      expect(viewerRow).toHaveAttribute("data-editable", "true");
      expect(ownerRow).toHaveAttribute("data-editable", "false");
    });
    expect(screen.queryByLabelText("grant.model.9")).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("f048_permission.grant.remove.9"),
    ).not.toBeInTheDocument();
    expect(ownerRow).toHaveTextContent("Owner");
  });

  it("renders protected and inherited grants as read-only and paginates by cursor", async () => {
    mockedGetGrants
      .mockResolvedValueOnce({
        data: [
          assignee("3", "DIRECT", {
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
        data: [assignee("4", "DIRECT", { subject: { type: "user", id: "8", name: "Bob" } })],
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
    expect(protectedRow).toHaveTextContent(
      "f048_permission.roster.parent_folder",
    );
    expect(protectedRow).not.toHaveTextContent("folder:parent-1");
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
    for (const action of ["use", "edit", "download", "rename"])
      expect(screen.queryByText(action)).not.toBeInTheDocument();
    expect(mockedGetSummary).toHaveBeenCalledWith(
      "knowledge_file",
      "file-1",
    );
    expect(mockedGetGrants).not.toHaveBeenCalled();
    expect(mockedGetModels).not.toHaveBeenCalled();
    expect(mockedMutate).not.toHaveBeenCalled();
  });
});
