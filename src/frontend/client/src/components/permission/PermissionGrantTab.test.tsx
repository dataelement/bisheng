import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  authorizeResource,
  getGrantableRelationModels,
  getKnowledgeSpaceGrantDepartments,
  getKnowledgeSpaceGrantUserGroups,
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
  getKnowledgeSpaceGrantDepartments: jest.fn(),
  getKnowledgeSpaceGrantUserGroups: jest.fn(),
  getResourcePermissions: jest.fn(),
  getResourceGrantDepartments: jest.fn(),
  getResourceGrantUserGroups: jest.fn(),
  getResourceGrantUsers: jest.fn(),
}));

const mockedAuthorizeResource = jest.mocked(authorizeResource);
const mockedGetGrantableRelationModels = jest.mocked(getGrantableRelationModels);
const mockedGetKnowledgeSpaceGrantDepartments = jest.mocked(getKnowledgeSpaceGrantDepartments);
const mockedGetKnowledgeSpaceGrantUserGroups = jest.mocked(getKnowledgeSpaceGrantUserGroups);
const mockedGetResourcePermissions = jest.mocked(getResourcePermissions);
const mockedGetResourceGrantDepartments = jest.mocked(getResourceGrantDepartments);
const mockedGetResourceGrantUserGroups = jest.mocked(getResourceGrantUserGroups);
const mockedGetResourceGrantUsers = jest.mocked(getResourceGrantUsers);

describe("PermissionGrantTab", () => {
  beforeAll(() => {
    class IntersectionObserverMock implements IntersectionObserver {
      readonly root = null;
      readonly rootMargin = "";
      readonly thresholds = [];
      disconnect = jest.fn();
      observe = jest.fn();
      takeRecords = jest.fn(() => []);
      unobserve = jest.fn();
    }
    Object.defineProperty(window, "IntersectionObserver", {
      writable: true,
      configurable: true,
      value: IntersectionObserverMock,
    });
    class ResizeObserverMock implements ResizeObserver {
      disconnect = jest.fn();
      observe = jest.fn();
      unobserve = jest.fn();
    }
    Object.defineProperty(globalThis, "ResizeObserver", {
      writable: true,
      configurable: true,
      value: ResizeObserverMock,
    });
  });

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
    mockedGetResourceGrantDepartments.mockResolvedValue([]);
    mockedGetKnowledgeSpaceGrantDepartments.mockResolvedValue([
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
    mockedGetKnowledgeSpaceGrantUserGroups.mockResolvedValue([]);
  });

  it("hides owner from knowledge space uniform grant options for every subject type", async () => {
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
    ]);

    render(
      <PermissionGrantTab
        resourceType="knowledge_space"
        resourceId="space-1"
        onSuccess={jest.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("com_permission.level_viewer")).toBeInTheDocument();
    });
    expect(screen.queryByText("com_permission.level_owner")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "com_permission.subject_department" }));
    expect(screen.queryByText("com_permission.level_owner")).not.toBeInTheDocument();

    expect(screen.queryByRole("button", { name: "com_permission.subject_user_group" })).not.toBeInTheDocument();
    expect(screen.queryByText("com_permission.level_owner")).not.toBeInTheDocument();
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
    expect(mockedGetKnowledgeSpaceGrantDepartments).toHaveBeenCalledWith(
      "space-1",
      { signal: expect.any(AbortSignal) },
    );
  });

  it("shows inherited child departments in the selected department summary", async () => {
    mockedGetKnowledgeSpaceGrantDepartments.mockResolvedValue([
      {
        id: 7,
        dept_id: "dept-7",
        name: "测试部门",
        parent_id: null,
        member_count: 3,
        children: [
          {
            id: 8,
            dept_id: "dept-8",
            name: "子部门",
            parent_id: 7,
            member_count: 1,
            children: [],
          },
        ],
      },
    ]);

    render(
      <PermissionGrantTab
        resourceType="knowledge_space"
        resourceId="space-1"
        onSuccess={jest.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "com_permission.subject_department" }));
    fireEvent.click(await screen.findByText("测试部门"));

    await waitFor(() => {
      expect(screen.getAllByText("测试部门").length).toBeGreaterThan(1);
      expect(screen.getByText("测试部门/子部门")).toBeInTheDocument();
    });
  });

  it("marks already granted departments as disabled without selecting them again", async () => {
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
      expect(checkbox).toHaveAttribute("data-state", "unchecked");
      expect(checkbox).toBeDisabled();
    });
    expect(screen.getByText("com_permission.already_granted")).toBeInTheDocument();

    fireEvent.click(departmentLabel);
    fireEvent.click(screen.getByRole("button", { name: "com_permission.action_submit" }));

    expect(mockedAuthorizeResource).not.toHaveBeenCalled();
  });

  it("marks already granted users as disabled without selecting them again", async () => {
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
      expect(checkbox).toHaveAttribute("data-state", "unchecked");
      expect(checkbox).toBeDisabled();
    });
    expect(screen.getByText("com_permission.already_granted")).toBeInTheDocument();

    fireEvent.click(userLabel);
    fireEvent.click(screen.getByRole("button", { name: "com_permission.action_submit" }));

    expect(mockedAuthorizeResource).not.toHaveBeenCalled();
  });

  it("hides user group grant targets even when historical user group grants exist", async () => {
    mockedGetResourcePermissions.mockResolvedValue([
      {
        subject_type: "user_group",
        subject_id: 9,
        subject_name: "测试用户组",
        relation: "viewer",
      },
    ] as any);
    mockedGetKnowledgeSpaceGrantUserGroups.mockResolvedValue([
      { id: 9, group_name: "测试用户组" },
    ]);

    render(
      <PermissionGrantTab
        resourceType="knowledge_space"
        resourceId="space-1"
        onSuccess={jest.fn()}
      />,
    );

    await waitFor(() => {
      expect(mockedGetResourcePermissions).toHaveBeenCalledWith("knowledge_space", "space-1");
    });

    expect(screen.queryByRole("button", { name: "com_permission.subject_user_group" })).not.toBeInTheDocument();
    expect(screen.queryByText("测试用户组")).not.toBeInTheDocument();
    expect(mockedGetKnowledgeSpaceGrantUserGroups).not.toHaveBeenCalled();
    expect(mockedGetResourceGrantUserGroups).not.toHaveBeenCalled();
    expect(mockedAuthorizeResource).not.toHaveBeenCalled();
  });
});
