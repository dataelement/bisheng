import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  authorizeResource,
  getGrantableRelationModels,
  getResourcePermissions,
  getResourceGrantDepartments,
  getResourceGrantUserGroups,
  getResourceGrantUsers,
} from "~/api/permission";
import { PermissionGrantTab } from "./PermissionGrantTab";

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

jest.mock("~/Providers", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock("~/api/permission", () => ({
  authorizeResource: jest.fn(),
  getGrantableRelationModels: jest.fn(),
  getResourcePermissions: jest.fn(),
  getResourceGrantDepartments: jest.fn(),
  getResourceGrantUserGroups: jest.fn(),
  getResourceGrantUsers: jest.fn(),
}));

const mockedAuthorizeResource = jest.mocked(authorizeResource);
const mockedGetGrantableRelationModels = jest.mocked(getGrantableRelationModels);
const mockedGetResourcePermissions = jest.mocked(getResourcePermissions);
const mockedGetResourceGrantDepartments = jest.mocked(getResourceGrantDepartments);
const mockedGetResourceGrantUserGroups = jest.mocked(getResourceGrantUserGroups);
const mockedGetResourceGrantUsers = jest.mocked(getResourceGrantUsers);

describe("PermissionGrantTab", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedAuthorizeResource.mockResolvedValue(null);
    mockedGetResourcePermissions.mockResolvedValue([]);
    mockedGetGrantableRelationModels.mockResolvedValue([
      {
        id: "viewer",
        name: "Viewer",
        relation: "viewer",
        permissions: [],
        is_system: true,
      },
    ]);
    mockedGetResourceGrantUsers.mockResolvedValue([]);
    mockedGetResourceGrantDepartments.mockResolvedValue([
      {
        id: 7,
        dept_id: "dept-7",
        name: "测试部门",
        parent_id: null,
        member_count: 3,
        children: [],
      },
    ]);
    mockedGetResourceGrantUserGroups.mockResolvedValue([]);
  });

  it("submits the current include-children checkbox value for department grants", async () => {
    render(
      <PermissionGrantTab
        resourceType="knowledge_space"
        resourceId="space-1"
        onSuccess={jest.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "com_permission.subject_department" }));
    fireEvent.click(await screen.findByText("测试部门"));
    fireEvent.click(screen.getByRole("checkbox", { name: "com_permission.include_children" }));
    fireEvent.click(screen.getByRole("button", { name: "com_permission.action_submit" }));

    await waitFor(() => {
      expect(mockedAuthorizeResource).toHaveBeenCalledWith(
        "knowledge_space",
        "space-1",
        [
          {
            subject_type: "department",
            subject_id: 7,
            relation: "viewer",
            model_id: "viewer",
            include_children: false,
          },
        ],
        [],
      );
    });
    expect(mockedGetResourceGrantDepartments).toHaveBeenCalledWith(
      "knowledge_space",
      "space-1",
      { signal: expect.any(AbortSignal) },
    );
  });

  it("marks already granted departments as checked without submitting them again", async () => {
    mockedGetResourcePermissions.mockResolvedValue([
      {
        subject_type: "department",
        subject_id: 7,
        subject_name: "测试部门",
        relation: "viewer",
        include_children: false,
      },
    ] as any);

    render(
      <PermissionGrantTab
        resourceType="knowledge_space"
        resourceId="space-1"
        onSuccess={jest.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "com_permission.subject_department" }));

    const departmentLabel = await screen.findByText("测试部门");
    const checkbox = departmentLabel.parentElement?.querySelector('[role="checkbox"]');

    await waitFor(() => {
      expect(checkbox).toHaveAttribute("data-state", "checked");
      expect(checkbox).toBeDisabled();
    });

    fireEvent.click(departmentLabel);
    fireEvent.click(screen.getByRole("button", { name: "com_permission.action_submit" }));

    expect(mockedAuthorizeResource).not.toHaveBeenCalled();
  });

  it("marks already granted users as checked without submitting them again", async () => {
    mockedGetResourcePermissions.mockResolvedValue([
      {
        subject_type: "user",
        subject_id: 8,
        subject_name: "Alice",
        relation: "viewer",
      },
    ] as any);
    mockedGetResourceGrantUsers.mockResolvedValue([
      { user_id: 8, user_name: "Alice" },
    ]);

    render(
      <PermissionGrantTab
        resourceType="knowledge_space"
        resourceId="space-1"
        onSuccess={jest.fn()}
      />,
    );

    const userLabel = await screen.findByText("Alice");
    const checkbox = userLabel.parentElement?.querySelector('[role="checkbox"]');

    await waitFor(() => {
      expect(checkbox).toHaveAttribute("data-state", "checked");
      expect(checkbox).toBeDisabled();
    });

    fireEvent.click(userLabel);
    fireEvent.click(screen.getByRole("button", { name: "com_permission.action_submit" }));

    expect(mockedAuthorizeResource).not.toHaveBeenCalled();
  });
});
