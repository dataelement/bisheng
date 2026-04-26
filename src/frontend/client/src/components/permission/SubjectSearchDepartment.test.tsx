import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { getDepartmentTree, getResourceGrantDepartments } from "~/api/permission";
import type { SelectedSubject } from "~/api/permission";
import { SubjectSearchDepartment } from "./SubjectSearchDepartment";

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

jest.mock("~/api/permission", () => ({
  getDepartmentTree: jest.fn(),
  getResourceGrantDepartments: jest.fn(),
}));

const mockedGetDepartmentTree = jest.mocked(getDepartmentTree);
const mockedGetResourceGrantDepartments = jest.mocked(getResourceGrantDepartments);

describe("SubjectSearchDepartment", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedGetDepartmentTree.mockResolvedValue([
      {
        id: 1,
        dept_id: "dept-1",
        name: "全集团",
        parent_id: null,
        children: [
          {
            id: 2,
            dept_id: "dept-2",
            name: "子部门",
            parent_id: 1,
            children: [],
          },
        ],
      },
    ]);
    mockedGetResourceGrantDepartments.mockResolvedValue([
      {
        id: 3,
        dept_id: "dept-3",
        name: "应用授权部门",
        parent_id: null,
        children: [],
      },
    ]);
  });

  it("shows descendants as checked when an ancestor grant includes child departments", async () => {
    const value: SelectedSubject[] = [
      {
        type: "department",
        id: 1,
        name: "全集团",
        include_children: true,
      },
    ];

    render(
      <SubjectSearchDepartment
        value={value}
        onChange={jest.fn()}
        includeChildren
        onIncludeChildrenChange={jest.fn()}
      />,
    );

    await waitFor(() => {
      expect(mockedGetDepartmentTree).toHaveBeenCalledTimes(1);
    });

    fireEvent.change(screen.getByPlaceholderText("com_permission.search_department"), {
      target: { value: "子部门" },
    });

    const childLabel = await screen.findByText("子部门");
    const childCheckbox = within(childLabel.parentElement as HTMLElement).getByRole("checkbox");

    expect(childCheckbox).toHaveAttribute("data-state", "checked");
  });

  it("materializes inherited selections before removing parent inheritance", async () => {
    const onChange = jest.fn();
    const onIncludeChildrenChange = jest.fn();

    render(
      <SubjectSearchDepartment
        value={[
          {
            type: "department",
            id: 1,
            name: "全集团",
            include_children: true,
          },
        ]}
        onChange={onChange}
        includeChildren
        onIncludeChildrenChange={onIncludeChildrenChange}
      />,
    );

    await waitFor(() => {
      expect(mockedGetDepartmentTree).toHaveBeenCalledTimes(1);
    });

    fireEvent.change(screen.getByPlaceholderText("com_permission.search_department"), {
      target: { value: "子部门" },
    });

    fireEvent.click(await screen.findByText("子部门"));

    expect(onIncludeChildrenChange).toHaveBeenCalledWith(false);
    expect(onChange).toHaveBeenCalledWith([
      {
        type: "department",
        id: 1,
        name: "全集团",
        include_children: false,
      },
      {
        type: "department",
        id: 2,
        name: "子部门",
        include_children: false,
      },
    ]);
  });

  it("uses resource-scoped department candidates when a resource is provided", async () => {
    render(
      <SubjectSearchDepartment
        value={[]}
        onChange={jest.fn()}
        includeChildren
        onIncludeChildrenChange={jest.fn()}
        resourceType="workflow"
        resourceId="wf-1"
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("应用授权部门")).toBeInTheDocument();
    });

    expect(mockedGetResourceGrantDepartments).toHaveBeenCalledWith(
      "workflow",
      "wf-1",
      { signal: expect.any(AbortSignal) },
    );
    expect(mockedGetDepartmentTree).not.toHaveBeenCalled();
  });
});
