import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  authorizeResource,
  getGrantableRelationModels,
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
  DropdownMenuItem: ({ children, onSelect }: any) => (
    <button type="button" onClick={onSelect}>{children}</button>
  ),
  DropdownMenuSeparator: () => <div />,
}));

const mockedGetGrantableRelationModels = jest.mocked(getGrantableRelationModels);
const mockedGetResourcePermissions = jest.mocked(getResourcePermissions);
const mockedAuthorizeResource = jest.mocked(authorizeResource);

describe("Client PermissionListTab", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedAuthorizeResource.mockResolvedValue(null);
    mockedGetGrantableRelationModels.mockResolvedValue([
      {
        id: "owner",
        name: "Owner",
        relation: "owner",
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
    });
  });
});
