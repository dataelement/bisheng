import { PermissionListTab } from "@/components/bs-comp/permission/PermissionListTab";
import { getDepartmentTreeApi } from "@/controllers/API/department";
import {
  authorizeResource,
  getGrantableRelationModelsApi,
  getResourcePermissions,
} from "@/controllers/API/permission";
import { fireEvent, render, screen, waitFor } from "@/test/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/controllers/API/department", () => ({
  getDepartmentTreeApi: vi.fn(),
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

vi.mock("@/components/bs-ui/dropdownMenu", () => ({
  DropdownMenu: ({ children }: any) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: any) => <div>{children}</div>,
  DropdownMenuContent: ({ children }: any) => <div>{children}</div>,
  DropdownMenuItem: ({ children, onSelect }: any) => (
    <button type="button" onClick={onSelect}>{children}</button>
  ),
}));

const mockedGetDepartmentTreeApi = vi.mocked(getDepartmentTreeApi);
const mockedGetGrantableRelationModelsApi = vi.mocked(getGrantableRelationModelsApi);
const mockedGetResourcePermissions = vi.mocked(getResourcePermissions);
const mockedAuthorizeResource = vi.mocked(authorizeResource);

describe("PermissionListTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedAuthorizeResource.mockResolvedValue(null as any);
    mockedGetDepartmentTreeApi.mockResolvedValue([]);
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
    expect(screen.queryByLabelText("action.revoke")).not.toBeInTheDocument();
  });

  it("allows owner actions when another owner remains", async () => {
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
    expect(screen.getAllByLabelText("action.revoke")).toHaveLength(2);
  });

  it("deletes every relation for the selected subject", async () => {
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
    fireEvent.click(screen.getAllByLabelText("action.revoke")[0]);

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
});
