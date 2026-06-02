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

const mockLocalize = (key: string) => key;

jest.mock("~/hooks", () => ({
  useLocalize: () => mockLocalize,
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
    if (!window.PointerEvent) {
      Object.defineProperty(window, "PointerEvent", {
        configurable: true,
        value: MouseEvent,
      });
    }
    if (!Element.prototype.scrollIntoView) {
      Element.prototype.scrollIntoView = jest.fn();
    }
    if (!Element.prototype.hasPointerCapture) {
      Element.prototype.hasPointerCapture = jest.fn(() => false);
    }
    if (!Element.prototype.setPointerCapture) {
      Element.prototype.setPointerCapture = jest.fn();
    }
    if (!Element.prototype.releasePointerCapture) {
      Element.prototype.releasePointerCapture = jest.fn();
    }
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

  const channelRelationModels = [
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
    {
      id: "manager",
      name: "Manager",
      relation: "manager",
      permissions: [],
      is_system: true,
    },
  ] as const;

  async function openRelationSelect() {
    const trigger = screen.getByRole("combobox");
    trigger.focus();
    fireEvent.keyDown(trigger, {
      key: "ArrowDown",
      code: "ArrowDown",
      keyCode: 40,
    });
    return await screen.findByRole("listbox");
  }

  it("keeps owner grant level available for channel user grants", async () => {
    render(
      <PermissionGrantTab
        resourceType="channel"
        resourceId="channel-1"
        onSuccess={jest.fn()}
        prefetchedGrantableModels={[...channelRelationModels]}
        prefetchedGrantableModelsLoaded
        skipGrantableModelsRequest
        fixedSubjectType="user"
      />,
    );

    const listbox = await openRelationSelect();

    expect(listbox).toHaveTextContent("com_permission.level_owner");
  });

  it.each([
    ["department", "部门"],
    ["user_group", "用户组"],
  ] as const)("hides owner grant level for channel %s grants", async (subjectType) => {
    render(
      <PermissionGrantTab
        resourceType="channel"
        resourceId="channel-1"
        onSuccess={jest.fn()}
        prefetchedGrantableModels={[...channelRelationModels]}
        prefetchedGrantableModelsLoaded
        skipGrantableModelsRequest
        fixedSubjectType={subjectType}
      />,
    );

    const listbox = await openRelationSelect();

    expect(listbox).not.toHaveTextContent("com_permission.level_owner");
    expect(listbox).toHaveTextContent("com_permission.level_viewer");
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

  it("shows inherited child departments in the selected department summary", async () => {
    mockedGetResourceGrantDepartments.mockResolvedValue([
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

  it("marks already granted user groups as disabled without selecting them again", async () => {
    mockedGetResourcePermissions.mockResolvedValue([
      {
        subject_type: "user_group",
        subject_id: 9,
        subject_name: "测试用户组",
        relation: "viewer",
      },
    ] as any);
    mockedGetResourceGrantUserGroups.mockResolvedValue([
      { id: 9, group_name: "测试用户组" },
    ]);

    render(
      <PermissionGrantTab
        resourceType="knowledge_space"
        resourceId="space-1"
        onSuccess={jest.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "com_permission.subject_user_group" }));

    const userGroupLabel = await screen.findByText("测试用户组");
    const checkbox = userGroupLabel.parentElement?.querySelector('[role="checkbox"]');

    await waitFor(() => {
      expect(checkbox).toHaveAttribute("data-state", "unchecked");
      expect(checkbox).toBeDisabled();
    });
    expect(screen.getByText("com_permission.already_granted")).toBeInTheDocument();

    fireEvent.click(userGroupLabel);
    fireEvent.click(screen.getByRole("button", { name: "com_permission.action_submit" }));

    expect(mockedAuthorizeResource).not.toHaveBeenCalled();
  });
});
