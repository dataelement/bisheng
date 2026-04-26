import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { getDepartmentTree } from "~/api/permission";
import type { SelectedSubject } from "~/api/permission";
import { SubjectSearchDepartment } from "./SubjectSearchDepartment";

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

jest.mock("~/api/permission", () => ({
  getDepartmentTree: jest.fn(),
  getKnowledgeSpaceGrantDepartments: jest.fn(),
}));

const mockedGetDepartmentTree = jest.mocked(getDepartmentTree);

describe("SubjectSearchDepartment", () => {
  beforeEach(() => {
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
});
