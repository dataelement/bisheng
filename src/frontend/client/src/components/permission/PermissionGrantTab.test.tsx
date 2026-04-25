import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  authorizeResource,
  getDepartmentTree,
  getGrantableRelationModels,
  getKnowledgeSpaceGrantDepartments,
  getKnowledgeSpaceGrantUserGroups,
  getKnowledgeSpaceGrantUsers,
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
  getDepartmentTree: jest.fn(),
  getGrantableRelationModels: jest.fn(),
  getKnowledgeSpaceGrantDepartments: jest.fn(),
  getKnowledgeSpaceGrantUserGroups: jest.fn(),
  getKnowledgeSpaceGrantUsers: jest.fn(),
}));

const mockedAuthorizeResource = jest.mocked(authorizeResource);
const mockedGetDepartmentTree = jest.mocked(getDepartmentTree);
const mockedGetGrantableRelationModels = jest.mocked(getGrantableRelationModels);
const mockedGetKnowledgeSpaceGrantDepartments = jest.mocked(getKnowledgeSpaceGrantDepartments);
const mockedGetKnowledgeSpaceGrantUserGroups = jest.mocked(getKnowledgeSpaceGrantUserGroups);
const mockedGetKnowledgeSpaceGrantUsers = jest.mocked(getKnowledgeSpaceGrantUsers);

describe("PermissionGrantTab", () => {
  beforeEach(() => {
    mockedAuthorizeResource.mockResolvedValue(null);
    mockedGetGrantableRelationModels.mockResolvedValue([
      {
        id: "viewer",
        name: "Viewer",
        relation: "viewer",
        permissions: [],
        is_system: true,
      },
    ]);
    mockedGetDepartmentTree.mockResolvedValue([
      {
        id: 7,
        dept_id: "dept-7",
        name: "测试部门",
        parent_id: null,
        member_count: 3,
        children: [],
      },
    ]);
    mockedGetKnowledgeSpaceGrantUsers.mockResolvedValue([]);
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
    mockedGetKnowledgeSpaceGrantUserGroups.mockResolvedValue([]);
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
});
