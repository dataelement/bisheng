import { PermissionListTab } from "@/components/bs-comp/permission/PermissionListTab";
import {
  authorizeResource,
  getGrantableRelationModelsApi,
  getResourcePermissions,
} from "@/controllers/API/permission";
import { fireEvent, render, screen, waitFor } from "@/test/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/controllers/API/permission", () => ({
  authorizeResource: vi.fn(),
  getGrantableRelationModelsApi: vi.fn(),
  getResourcePermissions: vi.fn(),
}));

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => promise),
}));

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  useToast: () => ({ message: vi.fn() }),
}));

vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: ({ onOk }: any) => onOk?.(vi.fn()),
}));

// Render the dropdown fully (trigger + content) so the action items are queryable
// without driving Radix open state. DropdownMenuSeparator is new in this view.
vi.mock("@/components/bs-ui/dropdownMenu", () => ({
  DropdownMenu: ({ children }: any) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: any) => <div>{children}</div>,
  DropdownMenuContent: ({ children }: any) => <div>{children}</div>,
  DropdownMenuItem: ({ children, onSelect }: any) => (
    <button type="button" onClick={onSelect}>{children}</button>
  ),
  DropdownMenuSeparator: () => <hr />,
}));

// The row name/caption are wrapped in a truncation Tooltip; stub the tooltip
// primitives so they render their children without needing a TooltipProvider.
vi.mock("@/components/bs-ui/tooltip", () => ({
  Tooltip: ({ children }: any) => <>{children}</>,
  TooltipTrigger: ({ children }: any) => <>{children}</>,
  // Render nothing for the (hover-only) tooltip body so the row label is not
  // duplicated in the DOM — the visible text lives in the trigger.
  TooltipContent: () => null,
  Portal: ({ children }: any) => <>{children}</>,
}));

const mockedGetGrantableRelationModelsApi = vi.mocked(getGrantableRelationModelsApi);
const mockedGetResourcePermissions = vi.mocked(getResourcePermissions);
const mockedAuthorizeResource = vi.mocked(authorizeResource);

describe("PermissionListTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedAuthorizeResource.mockResolvedValue(null as any);
    mockedGetGrantableRelationModelsApi.mockResolvedValue([
      {
        id: "viewer",
        name: "Viewer",
        relation: "viewer",
        permissions: [],
        is_system: true,
      },
    ] as any);
    mockedGetResourcePermissions.mockResolvedValue([
      {
        subject_type: "user",
        subject_id: 2,
        subject_name: "Alice",
        relation: "viewer",
        model_id: "viewer",
        model_name: "Viewer",
      },
    ] as any);
  });

  it("does not reload grantable relation models when permission entries load", async () => {
    render(
      <PermissionListTab
        resourceType="knowledge_space"
        resourceId="3215"
        refreshKey={0}
      />,
    );

    await screen.findByText("Alice");

    await waitFor(() => {
      expect(mockedGetResourcePermissions).toHaveBeenCalledTimes(1);
    });
    expect(mockedGetGrantableRelationModelsApi).toHaveBeenCalledTimes(1);
    expect(mockedGetGrantableRelationModelsApi).toHaveBeenCalledWith(
      "knowledge_space",
      "3215",
    );
  });

  it("reuses prefetched grantable relation models without refetching", async () => {
    render(
      <PermissionListTab
        resourceType="knowledge_space"
        resourceId="3215"
        refreshKey={0}
        prefetchedGrantableModels={[
          {
            id: "viewer",
            name: "Viewer",
            relation: "viewer",
            permissions: [],
            is_system: true,
          },
        ] as any}
        prefetchedGrantableModelsLoaded
        skipGrantableModelsRequest
      />,
    );

    await screen.findByText("Alice");

    expect(mockedGetGrantableRelationModelsApi).not.toHaveBeenCalled();
    expect(mockedGetResourcePermissions).toHaveBeenCalledTimes(1);
  });

  it("keeps the last owner row read-only", async () => {
    mockedGetResourcePermissions.mockResolvedValue([
      {
        subject_type: "user",
        subject_id: 2,
        subject_name: "Alice",
        relation: "owner",
        model_id: "owner",
        model_name: "Owner",
      },
    ] as any);

    render(
      <PermissionListTab
        resourceType="knowledge_space"
        resourceId="3215"
        refreshKey={0}
        fixedSubjectType="user"
      />,
    );

    await screen.findByText("Alice");
    expect(screen.queryByText("action.remove")).not.toBeInTheDocument();
  });

  it("allows owner actions when another owner remains", async () => {
    mockedGetGrantableRelationModelsApi.mockResolvedValue([
      {
        id: "owner",
        name: "Owner",
        relation: "owner",
        permissions: [],
        is_system: true,
      },
    ] as any);
    mockedGetResourcePermissions.mockResolvedValue([
      {
        subject_type: "user",
        subject_id: 2,
        subject_name: "Alice",
        relation: "owner",
        model_id: "owner",
        model_name: "Owner",
      },
      {
        subject_type: "user",
        subject_id: 3,
        subject_name: "Bob",
        relation: "owner",
        model_id: "owner",
        model_name: "Owner",
      },
    ] as any);

    render(
      <PermissionListTab
        resourceType="knowledge_space"
        resourceId="3215"
        refreshKey={0}
        fixedSubjectType="user"
      />,
    );

    await screen.findByText("Alice");
    expect(screen.getAllByText("action.remove")).toHaveLength(2);
  });

  it("does not expose existing models outside the grantable set as actions", async () => {
    mockedGetGrantableRelationModelsApi.mockResolvedValue([
      {
        id: "viewer",
        name: "Viewer",
        relation: "viewer",
        permissions: [],
        is_system: true,
      },
    ] as any);
    mockedGetResourcePermissions.mockResolvedValue([
      {
        subject_type: "user",
        subject_id: 2,
        subject_name: "Alice",
        relation: "owner",
        model_id: "owner",
        model_name: "Owner",
      },
      {
        subject_type: "user",
        subject_id: 3,
        subject_name: "Bob",
        relation: "owner",
        model_id: "owner",
        model_name: "Owner",
      },
    ] as any);

    render(
      <PermissionListTab
        resourceType="knowledge_space"
        resourceId="3215"
        refreshKey={0}
        fixedSubjectType="user"
      />,
    );

    await screen.findByText("Alice");
    expect(screen.queryByText("action.remove")).not.toBeInTheDocument();
    expect(mockedAuthorizeResource).not.toHaveBeenCalled();
  });

  it("deletes every relation for the selected subject", async () => {
    mockedGetGrantableRelationModelsApi.mockResolvedValue([
      {
        id: "viewer",
        name: "Viewer",
        relation: "viewer",
        permissions: [],
        is_system: true,
      },
      {
        id: "editor",
        name: "Editor",
        relation: "editor",
        permissions: [],
        is_system: true,
      },
    ] as any);
    mockedGetResourcePermissions.mockResolvedValue([
      {
        subject_type: "user",
        subject_id: 2,
        subject_name: "Alice",
        relation: "viewer",
        model_id: "viewer",
        model_name: "Viewer",
      },
      {
        subject_type: "user",
        subject_id: 2,
        subject_name: "Alice",
        relation: "editor",
        model_id: "editor",
        model_name: "Editor",
      },
      {
        subject_type: "user",
        subject_id: 3,
        subject_name: "Bob",
        relation: "viewer",
        model_id: "viewer",
        model_name: "Viewer",
      },
    ] as any);

    render(
      <PermissionListTab
        resourceType="knowledge_file"
        resourceId="file-1"
        refreshKey={0}
        fixedSubjectType="user"
      />,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Alice").length).toBeGreaterThan(0);
    });
    // The first delete item belongs to Alice's first row; deleting a subject
    // revokes every relation it holds.
    fireEvent.click(screen.getAllByText("action.remove")[0]);

    await waitFor(() => {
      expect(mockedAuthorizeResource).toHaveBeenCalledWith(
        "knowledge_file",
        "file-1",
        [],
        [
          {
            subject_type: "user",
            subject_id: 2,
            relation: "viewer",
          },
          {
            subject_type: "user",
            subject_id: 2,
            relation: "editor",
          },
        ],
      );
    });
  });

  it("deletes department include-children grants across subtree and exact variants", async () => {
    // The granted department's label is the full path the backend already put in
    // subject_name (F038) — no per-grant path-tree call.
    mockedGetResourcePermissions.mockResolvedValue([
      {
        subject_type: "department",
        subject_id: 7,
        subject_name: "研发部",
        relation: "viewer",
        model_id: "viewer",
        model_name: "Viewer",
        include_children: true,
      },
    ] as any);

    render(
      <PermissionListTab
        resourceType="knowledge_space"
        resourceId="space-1"
        refreshKey={0}
        fixedSubjectType="department"
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("研发部")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("action.remove"));

    await waitFor(() => {
      expect(mockedAuthorizeResource).toHaveBeenCalledWith(
        "knowledge_space",
        "space-1",
        [],
        [
          {
            subject_type: "department",
            subject_id: 7,
            relation: "viewer",
            include_children: true,
          },
          {
            subject_type: "department",
            subject_id: 7,
            relation: "viewer",
            include_children: false,
          },
        ],
      );
    });
  });
});
