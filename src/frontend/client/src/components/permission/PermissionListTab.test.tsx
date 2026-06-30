import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  authorizeResource,
  getGrantableRelationModels,
  getResourceGrantDepartments,
  getResourcePermissions,
} from "~/api/permission";
import { PermissionListTab } from "./PermissionListTab";

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

jest.mock("~/Providers", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
  useConfirm: () => jest.fn().mockResolvedValue(true),
}));

jest.mock("~/api/permission", () => ({
  authorizeResource: jest.fn(),
  getGrantableRelationModels: jest.fn(),
  getResourceGrantDepartments: jest.fn(),
  getResourcePermissions: jest.fn(),
}));

jest.mock("~/components/ui/Avatar", () => ({
  Avatar: ({ children }: any) => <div>{children}</div>,
  AvatarName: ({ name }: any) => <div>{name}</div>,
}));

jest.mock("~/components/ui/DropdownMenu", () => ({
  DropdownMenu: ({ children }: any) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: any) => <div>{children}</div>,
  DropdownMenuContent: ({ children }: any) => <div>{children}</div>,
  DropdownMenuItem: ({ children, onSelect, ...props }: any) => (
    <button type="button" onClick={onSelect} {...props}>{children}</button>
  ),
  DropdownMenuSeparator: () => <div />,
}));

const mockedGetGrantableRelationModels = jest.mocked(getGrantableRelationModels);
const mockedGetResourceGrantDepartments = jest.mocked(getResourceGrantDepartments);
const mockedGetResourcePermissions = jest.mocked(getResourcePermissions);
const mockedAuthorizeResource = jest.mocked(authorizeResource);

describe("Client PermissionListTab", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedAuthorizeResource.mockResolvedValue(null);
    mockedGetResourceGrantDepartments.mockResolvedValue([]);
    mockedGetGrantableRelationModels.mockResolvedValue([
      {
        id: "owner",
        name: "Owner",
        relation: "owner",
        permissions: [],
        is_system: true,
      },
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
    ]);
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
        resourceId="space-1"
        refreshKey={0}
        fixedSubjectType="user"
      />,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Alice").length).toBeGreaterThan(0);
    });
    await waitFor(() => {
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
    });
  });

  it("shows owner actions when another owner remains", async () => {
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
        resourceId="space-1"
        refreshKey={0}
        fixedSubjectType="user"
      />,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Alice").length).toBeGreaterThan(0);
    });
    expect(screen.getAllByLabelText("com_permission.remove")).toHaveLength(2);
  });

  it("deletes all relations for the selected subject", async () => {
    const onPermissionChanged = jest.fn();
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
        onPermissionChanged={onPermissionChanged}
      />,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Alice").length).toBeGreaterThan(0);
    });
    fireEvent.click(screen.getAllByLabelText("com_permission.remove")[0]);

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
      expect(onPermissionChanged).toHaveBeenCalledTimes(1);
    });
  });

  it("notifies parent after modifying a subject relation", async () => {
    const onPermissionChanged = jest.fn();
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

    render(
      <PermissionListTab
        resourceType="knowledge_space"
        resourceId="space-1"
        refreshKey={0}
        fixedSubjectType="user"
        onPermissionChanged={onPermissionChanged}
      />,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Alice").length).toBeGreaterThan(0);
    });
    fireEvent.click(screen.getByRole("button", { name: "com_permission.level_editor" }));

    await waitFor(() => {
      expect(mockedAuthorizeResource).toHaveBeenCalledWith(
        "knowledge_space",
        "space-1",
        [
          {
            subject_type: "user",
            subject_id: 2,
            relation: "editor",
            model_id: "editor",
          },
        ],
        [
          {
            subject_type: "user",
            subject_id: 2,
            relation: "viewer",
          },
        ],
      );
      expect(onPermissionChanged).toHaveBeenCalledTimes(1);
    });
  });

  it("uses backend-filtered grantable models when editing a subject relation", async () => {
    mockedGetGrantableRelationModels.mockResolvedValue([
      {
        id: "editor",
        name: "Editor",
        relation: "editor",
        permissions: [],
        is_system: true,
      },
      {
        id: "viewer",
        name: "Viewer",
        relation: "viewer",
        permissions: [],
        is_system: true,
      },
    ]);
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

    render(
      <PermissionListTab
        resourceType="folder"
        resourceId="folder-1"
        refreshKey={0}
        fixedSubjectType="user"
      />,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Alice").length).toBeGreaterThan(0);
    });

    expect(screen.getByRole("button", { name: "com_permission.level_editor" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "com_permission.level_manager" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "com_permission.level_owner" })).not.toBeInTheDocument();
  });

  it("shows folder-scoped permission items on modify model help", async () => {
    mockedGetGrantableRelationModels.mockResolvedValue([
      {
        id: "viewer",
        name: "Viewer",
        relation: "viewer",
        permissions: [],
        permissions_explicit: false,
        is_system: true,
      },
      {
        id: "custom_folder_editor",
        name: "Folder Editor",
        relation: "editor",
        permissions: ["rename_folder", "view_file"],
        permissions_explicit: true,
        is_system: false,
      },
    ]);
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

    render(
      <PermissionListTab
        resourceType="folder"
        resourceId="folder-1"
        refreshKey={0}
        fixedSubjectType="user"
      />,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Alice").length).toBeGreaterThan(0);
    });

    const help = screen.getByTestId("permission-model-help-folder-custom_folder_editor");
    expect(help).toHaveAttribute(
      "data-permission-summary",
      "com_permission.permission_item_rename_folder",
    );
  });

  it("deletes department include-children grants across subtree and exact variants", async () => {
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
    fireEvent.click(screen.getByLabelText("com_permission.remove"));

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

  it("uses an injected permission API instead of generic resource endpoints", async () => {
    const permissionApi = {
      getPermissions: jest.fn().mockResolvedValue([
        {
          subject_type: "user",
          subject_id: 2,
          subject_name: "Alice",
          relation: "viewer",
          model_id: "viewer",
          model_name: "Viewer",
        },
      ]),
      authorize: jest.fn(),
      getGrantableRelationModels: jest.fn().mockResolvedValue([
        {
          id: "viewer",
          name: "Viewer",
          relation: "viewer",
          permissions: [],
          is_system: true,
        },
      ]),
      getGrantDepartments: jest.fn().mockResolvedValue([]),
    };

    render(
      <PermissionListTab
        resourceType="channel"
        resourceId="channel-1"
        refreshKey={0}
        fixedSubjectType="user"
        permissionApi={permissionApi as any}
      />,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Alice").length).toBeGreaterThan(0);
    });
    expect(permissionApi.getPermissions).toHaveBeenCalledWith("channel", "channel-1");
    expect(permissionApi.getGrantableRelationModels).toHaveBeenCalledWith("channel", "channel-1");
    expect(mockedGetResourcePermissions).not.toHaveBeenCalled();
    expect(mockedGetGrantableRelationModels).not.toHaveBeenCalled();
  });

  it("hides historical user group permission entries", async () => {
    mockedGetResourcePermissions.mockResolvedValue([
      {
        subject_type: "user_group",
        subject_id: 9,
        subject_name: "测试用户组",
        subject_member_names: ["Alice", "Bob"],
        relation: "viewer",
        model_id: "viewer",
        model_name: "Viewer",
      },
    ] as any);

    render(
      <PermissionListTab
        resourceType="knowledge_space"
        resourceId="space-1"
        refreshKey={0}
      />,
    );

    await waitFor(() => {
      expect(mockedGetResourcePermissions).toHaveBeenCalledWith("knowledge_space", "space-1");
    });

    expect(screen.queryByRole("button", { name: "com_permission.subject_user_group" })).not.toBeInTheDocument();
    expect(screen.queryByText("测试用户组")).not.toBeInTheDocument();
    expect(screen.queryByText("Alice、Bob")).not.toBeInTheDocument();
    expect(screen.getByText("com_permission.empty_permissions")).toBeInTheDocument();
  });
});
