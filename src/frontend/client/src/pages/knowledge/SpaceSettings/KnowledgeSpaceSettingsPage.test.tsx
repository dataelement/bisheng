import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import {
  createSpaceApi,
  getKnowledgeSpaceAutoTagVisibilityApi,
  getSpaceInfoApi,
  SpaceRole,
  updateSpaceApi,
  VisibilityType,
} from "~/api/knowledge";
import type { KnowledgeSpace } from "~/api/knowledge";
import {
  authorizeResource,
  checkPermission,
  getCreationGrantableRelationModels,
  getGrantableRelationModels,
  getResourcePermissions,
} from "~/api/permission";
import { KnowledgeSpaceSettingsPage } from "./KnowledgeSpaceSettingsPage";

const mockShowToast = jest.fn();

jest.mock("~/Providers", () => ({
  useConfirm: () => jest.fn().mockResolvedValue(true),
  useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
  useAuthContext: () => ({
    user: {
      id: 99,
      name: "Current user",
      username: "current",
      email: "current@example.com",
    },
  }),
}));

jest.mock("~/components/permission/RelationSelect", () => ({
  RelationSelect: ({
    value,
    onChange,
    options,
    disabled,
  }: {
    value: string;
    onChange: (value: string) => void;
    options: Array<{ id: string; name: string }>;
    disabled?: boolean;
  }) => (
    <select
      aria-label="permission-model"
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
    >
      {options.map((option) => (
        <option key={option.id} value={option.id}>
          {option.name}
        </option>
      ))}
    </select>
  ),
}));

jest.mock("~/components/permission/SubjectSearchUser", () => ({
  SubjectSearchUser: ({
    onChange,
  }: {
    onChange: (subjects: Array<Record<string, unknown>>) => void;
  }) => (
    <button
      type="button"
      onClick={() => onChange([{ type: "user", id: 9, name: "Ada" }])}
    >
      select-user
    </button>
  ),
}));
jest.mock("~/components/permission/SubjectSearchDepartment", () => ({
  SubjectSearchDepartment: ({
    includeChildren,
    onChange,
  }: {
    includeChildren: boolean;
    onChange: (subjects: Array<Record<string, unknown>>) => void;
  }) => (
    <button
      type="button"
      onClick={() =>
        onChange([
          {
            type: "department",
            id: 8,
            name: "Platform",
            include_children: includeChildren,
          },
        ])
      }
    >
      select-department
    </button>
  ),
}));
jest.mock("~/components/permission/SubjectSearchUserGroup", () => ({
  SubjectSearchUserGroup: () => <div data-testid="subject-groups" />,
}));
jest.mock("~/components/permission/PermissionDraftEditor", () => ({
  PermissionDraftEditor: ({
    value,
    onChange,
  }: {
    value: Array<Record<string, unknown>>;
    onChange: (rows: Array<Record<string, unknown>>) => void;
  }) => (
    <div data-testid="permission-editor">
      <span>{value.length}</span>
      <span data-testid="draft-relations">
        {value.map((row) => String(row.relation)).join(",")}
      </span>
      {value.length > 0 && (
        <button
          type="button"
          onClick={() =>
            onChange([{ ...value[0], relation: "editor", modelId: "editor" }])
          }
        >
          change-relation
        </button>
      )}
    </div>
  ),
}));

jest.mock("~/api/knowledge", () => {
  const actual = jest.requireActual("~/api/knowledge");
  return {
    ...actual,
    createSpaceApi: jest.fn(),
    getKnowledgeSpaceAutoTagVisibilityApi: jest.fn(),
    getKnowledgeSpaceTagLibrariesApi: jest.fn(),
    getKnowledgeSpaceTagLibraryDetailApi: jest.fn(),
    getSpaceInfoApi: jest.fn(),
    updateSpaceApi: jest.fn(),
  };
});

jest.mock("~/api/permission", () => {
  const actual = jest.requireActual("~/api/permission");
  return {
    ...actual,
    authorizeResource: jest.fn(),
    checkPermission: jest.fn(),
    getCreationGrantableRelationModels: jest.fn(),
    getGrantableRelationModels: jest.fn(),
    getResourcePermissions: jest.fn(),
  };
});

const mockedCreateSpace = createSpaceApi as jest.MockedFunction<
  typeof createSpaceApi
>;
const mockedGetAutoTagVisibility =
  getKnowledgeSpaceAutoTagVisibilityApi as jest.MockedFunction<
    typeof getKnowledgeSpaceAutoTagVisibilityApi
  >;
const mockedGetSpaceInfo = getSpaceInfoApi as jest.MockedFunction<
  typeof getSpaceInfoApi
>;
const mockedUpdateSpace = updateSpaceApi as jest.MockedFunction<
  typeof updateSpaceApi
>;
const mockedAuthorize = authorizeResource as jest.MockedFunction<
  typeof authorizeResource
>;
const mockedCheckPermission = checkPermission as jest.MockedFunction<
  typeof checkPermission
>;
const mockedGetCreationModels =
  getCreationGrantableRelationModels as jest.MockedFunction<
    typeof getCreationGrantableRelationModels
  >;
const mockedGetModels = getGrantableRelationModels as jest.MockedFunction<
  typeof getGrantableRelationModels
>;
const mockedGetPermissions = getResourcePermissions as jest.MockedFunction<
  typeof getResourcePermissions
>;

const relationModels = [
  {
    id: "editor",
    name: "Editor",
    relation: "editor" as const,
    permissions: ["edit_space"],
    is_system: true,
  },
];

const viewerRelationModel = {
  id: "viewer",
  name: "Viewer",
  relation: "viewer" as const,
  permissions: ["read_space"],
  is_system: true,
};

const ownerOnlyRelationModels = [
  {
    id: "owner",
    name: "Owner",
    relation: "owner" as const,
    permissions: ["manage_space_relation"],
    is_system: true,
  },
];

const baseSpace: KnowledgeSpace = {
  id: "7",
  name: "Product docs",
  description: "Current description",
  visibility: VisibilityType.APPROVAL,
  creator: "Owner",
  creatorId: "1",
  memberCount: 1,
  fileCount: 0,
  totalFileCount: 0,
  role: SpaceRole.CREATOR,
  isPinned: false,
  createdAt: "",
  updatedAt: "",
  tags: [],
  isReleased: true,
};

function renderPage(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="/knowledge/create"
            element={<KnowledgeSpaceSettingsPage />}
          />
          <Route
            path="/knowledge/space/:spaceId/settings"
            element={<KnowledgeSpaceSettingsPage />}
          />
          <Route
            path="/knowledge/space/:spaceId"
            element={<div>space-detail</div>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function mockEditCapabilities(edit: boolean, manage: boolean) {
  mockedCheckPermission.mockImplementation(
    async (_type, _id, _relation, permissionId) => ({
      allowed: permissionId === "edit_space" ? edit : manage,
    }),
  );
}

describe("KnowledgeSpaceSettingsPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedGetAutoTagVisibility.mockResolvedValue({ visible: false });
    mockedGetCreationModels.mockResolvedValue(relationModels);
    mockedGetModels.mockResolvedValue(relationModels);
    mockedGetPermissions.mockResolvedValue([]);
    mockedGetSpaceInfo.mockResolvedValue(baseSpace);
    mockedUpdateSpace.mockResolvedValue(baseSpace);
    mockedAuthorize.mockResolvedValue({
      syncedUserCount: 0,
      affectedMemberCount: 0,
      directAppliedCount: 1,
      inviteCreatedCount: 0,
      inviteExistingCount: 0,
      failedCount: 0,
      results: [],
    });
  });

  it("fills the available content area without a fixed page width", async () => {
    renderPage("/knowledge/create");

    const settingsPage = await screen.findByTestId(
      "knowledge-space-settings-page",
    );
    const settingsSurface = settingsPage.firstElementChild;
    expect(settingsSurface?.className).toContain("w-full");
    expect(settingsSurface?.className).not.toContain("max-w-[1368px]");
    expect(
      screen.getByPlaceholderText(
        "com_subscription.enter_knowledge_space_name",
      ).className,
    ).toContain("bg-white");
    expect(
      screen.getByPlaceholderText(
        "com_subscription.enter_knowledge_space_description",
      ).className,
    ).toContain("bg-white");
  });

  it("uses server capabilities for manager, editor-only, and read-only visibility", async () => {
    mockEditCapabilities(true, true);
    const manager = renderPage("/knowledge/space/7/settings");
    expect(await screen.findByTestId("permission-section")).not.toBeNull();
    manager.unmount();

    mockEditCapabilities(true, false);
    const editor = renderPage("/knowledge/space/7/settings");
    await screen.findByDisplayValue("Product docs");
    expect(screen.queryByTestId("permission-section")).toBeNull();
    expect(
      (screen.getByDisplayValue("Product docs") as HTMLInputElement).disabled,
    ).toBe(false);
    editor.unmount();

    mockEditCapabilities(false, false);
    renderPage("/knowledge/space/7/settings");
    expect(
      ((await screen.findByDisplayValue("Product docs")) as HTMLInputElement)
        .disabled,
    ).toBe(true);
    expect(screen.queryByTestId("permission-section")).toBeNull();
    expect(
      (
        screen.getByRole("button", {
          name: "com_unified_permission.save",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });

  it("defaults create sharing to approval and hides authorization while private", async () => {
    renderPage("/knowledge/create");
    expect(await screen.findByTestId("authorization-list")).not.toBeNull();
    expect(
      (
        screen.getByRole("switch", {
          name: "com_unified_permission.review_join",
        }) as HTMLButtonElement
      ).getAttribute("aria-checked"),
    ).toBe("true");

    fireEvent.click(
      screen.getByRole("radio", {
        name: /com_unified_permission\.private/,
      }),
    );
    expect(screen.queryByTestId("authorization-list")).toBeNull();

    fireEvent.click(
      screen.getByRole("radio", {
        name: /com_unified_permission\.shared/,
      }),
    );
    expect(
      (
        screen.getByRole("switch", {
          name: "com_unified_permission.review_join",
        }) as HTMLButtonElement
      ).getAttribute("aria-checked"),
    ).toBe("true");
  });

  it("keeps department spaces shared while join review and member permissions remain configurable", async () => {
    mockEditCapabilities(true, true);
    mockedGetSpaceInfo.mockResolvedValue({
      ...baseSpace,
      spaceKind: "department",
      visibility: VisibilityType.APPROVAL,
    });

    renderPage("/knowledge/space/7/settings");

    const privateOption = await screen.findByRole("radio", {
      name: /com_unified_permission\.private/,
    });
    const sharedOption = screen.getByRole("radio", {
      name: /com_unified_permission\.shared/,
    });
    const reviewJoin = screen.getByRole("switch", {
      name: "com_unified_permission.review_join",
    });

    expect((privateOption as HTMLButtonElement).disabled).toBe(true);
    expect(sharedOption.getAttribute("data-state")).toBe("checked");
    expect((reviewJoin as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByTestId("authorization-list")).not.toBeNull();

    fireEvent.click(reviewJoin);
    fireEvent.click(
      screen.getByRole("button", { name: "com_unified_permission.save" }),
    );

    await waitFor(() =>
      expect(mockedUpdateSpace).toHaveBeenCalledWith(
        "7",
        expect.objectContaining({ auth_type: VisibilityType.PUBLIC }),
      ),
    );
  });

  it("normalizes historical private department spaces back to shared approval on save", async () => {
    mockEditCapabilities(true, true);
    mockedGetSpaceInfo.mockResolvedValue({
      ...baseSpace,
      spaceKind: "department",
      visibility: VisibilityType.PRIVATE,
    });

    renderPage("/knowledge/space/7/settings");

    const privateOption = await screen.findByRole("radio", {
      name: /com_unified_permission\.private/,
    });
    const sharedOption = screen.getByRole("radio", {
      name: /com_unified_permission\.shared/,
    });
    const reviewJoin = screen.getByRole("switch", {
      name: "com_unified_permission.review_join",
    });

    expect((privateOption as HTMLButtonElement).disabled).toBe(true);
    expect(sharedOption.getAttribute("data-state")).toBe("checked");
    expect(reviewJoin.getAttribute("data-state")).toBe("checked");

    fireEvent.click(
      screen.getByRole("button", { name: "com_unified_permission.save" }),
    );

    await waitFor(() =>
      expect(mockedUpdateSpace).toHaveBeenCalledWith(
        "7",
        expect.objectContaining({ auth_type: VisibilityType.APPROVAL }),
      ),
    );
  });

  it("applies the model selected in the reused authorization dialog", async () => {
    mockedGetCreationModels.mockResolvedValue([
      relationModels[0],
      viewerRelationModel,
    ]);
    renderPage("/knowledge/create");
    await screen.findByTestId("permission-section");

    fireEvent.click(
      screen.getByRole("button", {
        name: "com_unified_permission.add_authorization",
      }),
    );
    fireEvent.click(await screen.findByText("select-user"));
    fireEvent.change(
      screen.getByRole("combobox", { name: "permission-model" }),
      {
        target: { value: "editor" },
      },
    );
    const addButtons = screen.getAllByRole("button", {
      name: "com_unified_permission.add_authorization",
    });
    fireEvent.click(addButtons[addButtons.length - 1]);

    expect(screen.getByTestId("draft-relations").textContent).toContain(
      "editor",
    );
  });

  it("keeps the created resource and retries only authorization after initial grant failure", async () => {
    mockedCreateSpace.mockResolvedValue({
      ...baseSpace,
      id: "88",
      initialPermissionResult: {
        status: "failed",
        errorCode: 21009,
        directAppliedCount: 0,
        inviteCreatedCount: 0,
        inviteExistingCount: 0,
        failedCount: 1,
        results: [],
      },
    });
    renderPage("/knowledge/create");
    await screen.findByTestId("permission-section");
    fireEvent.click(
      screen.getByRole("button", {
        name: "com_unified_permission.add_authorization",
      }),
    );
    fireEvent.click(await screen.findByText("select-user"));
    const addButtons = screen.getAllByRole("button", {
      name: "com_unified_permission.add_authorization",
    });
    fireEvent.click(addButtons[addButtons.length - 1]);
    fireEvent.change(
      screen.getByPlaceholderText(
        "com_subscription.enter_knowledge_space_name",
      ),
      {
        target: { value: "New docs" },
      },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "com_unified_permission.confirm_create",
      }),
    );

    expect(
      await screen.findByText(
        "com_unified_permission.resource_created_permission_failed",
      ),
    ).not.toBeNull();
    expect(mockedCreateSpace).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("button", {
        name: "com_unified_permission.enter_space",
      }),
    ).not.toBeNull();
    fireEvent.click(
      screen.getByRole("button", {
        name: "com_unified_permission.retry_permission",
      }),
    );
    await waitFor(() => expect(mockedAuthorize).toHaveBeenCalledTimes(1));
    expect(mockedCreateSpace).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("space-detail")).not.toBeNull();
  });

  it("uses the current include-children value for departments selected earlier", async () => {
    mockedCreateSpace.mockResolvedValue({ ...baseSpace, id: "89" });
    renderPage("/knowledge/create");
    await screen.findByTestId("permission-section");

    fireEvent.click(
      screen.getByRole("button", {
        name: "com_unified_permission.add_authorization",
      }),
    );
    fireEvent.mouseDown(
      screen.getByRole("tab", { name: "com_permission.subject_department" }),
      { button: 0, ctrlKey: false },
    );
    fireEvent.click(await screen.findByText("select-department"));
    fireEvent.click(
      screen.getByRole("checkbox", { name: "com_permission.include_children" }),
    );
    const addButtons = screen.getAllByRole("button", {
      name: "com_unified_permission.add_authorization",
    });
    fireEvent.click(addButtons[addButtons.length - 1]);
    fireEvent.change(
      screen.getByPlaceholderText(
        "com_subscription.enter_knowledge_space_name",
      ),
      {
        target: { value: "Scoped docs" },
      },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "com_unified_permission.confirm_create",
      }),
    );

    await waitFor(() =>
      expect(mockedCreateSpace).toHaveBeenCalledWith(
        expect.objectContaining({
          initialPermissions: {
            grants: [
              expect.objectContaining({
                subject_type: "department",
                subject_id: 8,
                include_children: false,
                relation: "editor",
              }),
            ],
          },
        }),
      ),
    );
  });

  it("disables department and user-group selection when only owner is grantable", async () => {
    mockedGetCreationModels.mockResolvedValue(ownerOnlyRelationModels);
    renderPage("/knowledge/create");
    await screen.findByTestId("permission-section");

    fireEvent.click(
      screen.getByRole("button", {
        name: "com_unified_permission.add_authorization",
      }),
    );

    expect(
      (
        screen.getByRole("tab", {
          name: "com_permission.subject_department",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      (
        screen.getByRole("tab", {
          name: "com_permission.subject_user_group",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      (
        screen.getByRole("tab", {
          name: "com_permission.subject_user",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
  });

  it("sends only touched permission changes and skips authorize when converted to private", async () => {
    mockEditCapabilities(true, true);
    mockedGetPermissions.mockResolvedValue([
      {
        subject_type: "user",
        subject_id: 9,
        subject_name: "Ada",
        relation: "owner",
        model_id: "owner",
        is_creator: false,
      },
    ]);
    const view = renderPage("/knowledge/space/7/settings");
    await screen.findByText("change-relation");
    fireEvent.click(screen.getByText("change-relation"));
    fireEvent.click(
      screen.getByRole("button", { name: "com_unified_permission.save" }),
    );
    await waitFor(() =>
      expect(mockedAuthorize).toHaveBeenCalledWith(
        "knowledge_space",
        "7",
        [expect.objectContaining({ subject_id: 9, relation: "editor" })],
        [expect.objectContaining({ subject_id: 9, relation: "owner" })],
      ),
    );
    view.unmount();

    jest.clearAllMocks();
    mockedGetAutoTagVisibility.mockResolvedValue({ visible: false });
    mockedGetSpaceInfo.mockResolvedValue(baseSpace);
    mockedGetModels.mockResolvedValue(relationModels);
    mockedGetPermissions.mockResolvedValue([]);
    mockedUpdateSpace.mockResolvedValue({
      ...baseSpace,
      visibility: VisibilityType.PRIVATE,
    });
    mockedAuthorize.mockResolvedValue({
      syncedUserCount: 0,
      affectedMemberCount: 0,
      directAppliedCount: 1,
      inviteCreatedCount: 0,
      inviteExistingCount: 0,
      failedCount: 0,
      results: [],
    });
    mockEditCapabilities(true, true);
    renderPage("/knowledge/space/7/settings");
    await screen.findByTestId("permission-section");
    fireEvent.click(
      screen.getByRole("radio", {
        name: /com_unified_permission\.private/,
      }),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("authorization-list")).toBeNull(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "com_unified_permission.save" }),
    );
    await waitFor(() =>
      expect(mockedUpdateSpace).toHaveBeenCalledWith(
        "7",
        expect.objectContaining({ auth_type: VisibilityType.PRIVATE }),
      ),
    );
    expect(mockedAuthorize).not.toHaveBeenCalled();
  });

  it("stays on edit settings and does not report success for partial authorization failure", async () => {
    mockEditCapabilities(true, true);
    mockedGetPermissions.mockResolvedValue([
      {
        subject_type: "user",
        subject_id: 9,
        subject_name: "Ada",
        relation: "owner",
        model_id: "owner",
        is_creator: false,
      },
    ]);
    mockedAuthorize.mockResolvedValue({
      syncedUserCount: 0,
      affectedMemberCount: 0,
      directAppliedCount: 0,
      inviteCreatedCount: 0,
      inviteExistingCount: 0,
      failedCount: 1,
      results: [
        {
          operation: "grant",
          subjectType: "user",
          subjectId: 9,
          relation: "editor",
          modelId: "editor",
          outcome: "failed",
          approvalInstanceId: null,
          errorCode: 18118,
          errorMessage: "failed",
        },
      ],
    });
    renderPage("/knowledge/space/7/settings");
    await screen.findByText("change-relation");
    fireEvent.click(screen.getByText("change-relation"));
    fireEvent.click(
      screen.getByRole("button", { name: "com_unified_permission.save" }),
    );

    await waitFor(() =>
      expect(mockShowToast).toHaveBeenCalledWith(
        expect.objectContaining({ message: "com_invite.partial_failed" }),
      ),
    );
    expect(screen.queryByText("space-detail")).toBeNull();
    expect(mockShowToast).not.toHaveBeenCalledWith(
      expect.objectContaining({ message: "com_knowledge.space_updated" }),
    );
  });
});
