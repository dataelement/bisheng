import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";

import { getResourceGrantDepartments } from "~/api/permission";
import type { SelectedSubject } from "~/api/permission";
import { SubjectSearchDepartment } from "./SubjectSearchDepartment";

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

jest.mock("~/api/permission", () => ({
  getResourceGrantDepartments: jest.fn(),
}));

const mockedGetResourceGrantDepartments = jest.mocked(getResourceGrantDepartments);

const threeLevelDepartments = [
  {
    id: 1,
    dept_id: "dept-1",
    name: "集团",
    parent_id: null,
    children: [
      {
        id: 2,
        dept_id: "dept-2",
        name: "A事业部",
        parent_id: 1,
        children: [
          {
            id: 3,
            dept_id: "dept-3",
            name: "A子部门",
            parent_id: 2,
            children: [],
          },
        ],
      },
      {
        id: 4,
        dept_id: "dept-4",
        name: "B事业部",
        parent_id: 1,
        children: [
          {
            id: 5,
            dept_id: "dept-5",
            name: "B子部门",
            parent_id: 4,
            children: [],
          },
        ],
      },
    ],
  },
];

function ControlledSingleDepartmentTree({
  onChange,
  loadDepartments,
}: {
  onChange: (value: SelectedSubject[]) => void;
  loadDepartments: () => Promise<typeof threeLevelDepartments>;
}) {
  const [value, setValue] = useState<SelectedSubject[]>([]);

  return (
    <SubjectSearchDepartment
      value={value}
      onChange={(nextValue) => {
        setValue(nextValue);
        onChange(nextValue);
      }}
      includeChildren
      onIncludeChildrenChange={jest.fn()}
      selectionMode="single"
      loadDepartments={loadDepartments}
    />
  );
}

describe("SubjectSearchDepartment", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedGetResourceGrantDepartments.mockResolvedValue([
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
        resourceType="workflow"
        resourceId="wf-1"
        includeChildren
        onIncludeChildrenChange={jest.fn()}
      />,
    );

    await waitFor(() => {
      expect(mockedGetResourceGrantDepartments).toHaveBeenCalledWith(
        "workflow",
        "wf-1",
        { signal: expect.any(AbortSignal) },
      );
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
        resourceType="workflow"
        resourceId="wf-1"
        includeChildren
        onIncludeChildrenChange={onIncludeChildrenChange}
      />,
    );

    await waitFor(() => {
      expect(mockedGetResourceGrantDepartments).toHaveBeenCalledTimes(1);
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
        name: "全集团/子部门",
        include_children: false,
      },
    ]);
  });

  it("reports selected descendant names for include-children department summaries", async () => {
    const onSelectionSummaryChange = jest.fn();

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
        onChange={jest.fn()}
        resourceType="workflow"
        resourceId="wf-1"
        includeChildren
        onIncludeChildrenChange={jest.fn()}
        onSelectionSummaryChange={onSelectionSummaryChange}
      />,
    );

    await waitFor(() => {
      expect(onSelectionSummaryChange).toHaveBeenLastCalledWith([
        {
          type: "department",
          id: 1,
          name: "全集团",
          include_children: false,
        },
        {
          type: "department",
          id: 2,
          name: "全集团/子部门",
          include_children: false,
        },
      ]);
    });
  });

  it("shows already granted departments as disabled without selecting them", async () => {
    render(
      <SubjectSearchDepartment
        value={[]}
        onChange={jest.fn()}
        resourceType="workflow"
        resourceId="wf-1"
        includeChildren
        onIncludeChildrenChange={jest.fn()}
        disabledIds={[1]}
      />,
    );

    const departmentLabel = await screen.findByText("全集团");
    const checkbox = within(departmentLabel.parentElement as HTMLElement).getByRole("checkbox");

    expect(checkbox).toHaveAttribute("data-state", "unchecked");
    expect(checkbox).toBeDisabled();
    expect(screen.getByText("com_permission.already_granted")).toBeInTheDocument();
  });

  it("uses resource-scoped department candidates when a resource is provided", async () => {
    mockedGetResourceGrantDepartments.mockResolvedValue([
      {
        id: 3,
        dept_id: "dept-3",
        name: "应用授权部门",
        parent_id: null,
        children: [],
      },
    ]);

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
  });

  it("shows every ancestor as indeterminate while keeping only the selected child", async () => {
    const onChange = jest.fn();
    const loadDepartments = jest.fn().mockResolvedValue(threeLevelDepartments);

    render(
      <ControlledSingleDepartmentTree
        onChange={onChange}
        loadDepartments={loadDepartments}
      />,
    );

    const rootLabel = await screen.findByText("集团");
    fireEvent.click(within(rootLabel.parentElement as HTMLElement).getByRole("button"));

    const branchALabel = await screen.findByText("A事业部");
    const branchBLabel = await screen.findByText("B事业部");
    fireEvent.click(within(branchALabel.parentElement as HTMLElement).getByRole("button"));
    fireEvent.click(within(branchBLabel.parentElement as HTMLElement).getByRole("button"));

    const leafALabel = await screen.findByText("A子部门");
    const leafBLabel = await screen.findByText("B子部门");
    fireEvent.click(leafALabel);

    expect(onChange).toHaveBeenLastCalledWith([
      {
        type: "department",
        id: 3,
        name: "A子部门",
        include_children: true,
      },
    ]);
    expect(within(rootLabel.parentElement as HTMLElement).getByRole("checkbox"))
      .toHaveAttribute("data-state", "indeterminate");
    expect(within(branchALabel.parentElement as HTMLElement).getByRole("checkbox"))
      .toHaveAttribute("data-state", "indeterminate");
    expect(within(leafALabel.parentElement as HTMLElement).getByRole("checkbox"))
      .toHaveAttribute("data-state", "checked");
    expect(within(branchBLabel.parentElement as HTMLElement).getByRole("checkbox"))
      .toHaveAttribute("data-state", "unchecked");

    fireEvent.click(leafBLabel);

    expect(onChange).toHaveBeenLastCalledWith([
      {
        type: "department",
        id: 5,
        name: "B子部门",
        include_children: true,
      },
    ]);
    expect(within(branchALabel.parentElement as HTMLElement).getByRole("checkbox"))
      .toHaveAttribute("data-state", "unchecked");
    expect(within(branchBLabel.parentElement as HTMLElement).getByRole("checkbox"))
      .toHaveAttribute("data-state", "indeterminate");

    fireEvent.click(leafBLabel);

    expect(onChange).toHaveBeenLastCalledWith([]);
    expect(within(rootLabel.parentElement as HTMLElement).getByRole("checkbox"))
      .toHaveAttribute("data-state", "unchecked");
    expect(within(branchBLabel.parentElement as HTMLElement).getByRole("checkbox"))
      .toHaveAttribute("data-state", "unchecked");
  });

  it("does not add ancestor indeterminate state in multiple selection mode", async () => {
    render(
      <SubjectSearchDepartment
        value={[{ type: "department", id: 2, name: "子部门" }]}
        onChange={jest.fn()}
        resourceType="workflow"
        resourceId="wf-1"
        includeChildren
        onIncludeChildrenChange={jest.fn()}
        selectionMode="multiple"
      />,
    );

    const rootLabel = await screen.findByText("全集团");
    const rootRow = rootLabel.parentElement as HTMLElement;
    expect(within(rootRow).getByRole("checkbox"))
      .toHaveAttribute("data-state", "unchecked");

    fireEvent.click(within(rootRow).getByRole("button"));
    const childLabel = await screen.findByText("子部门");
    expect(within(childLabel.parentElement as HTMLElement).getByRole("checkbox"))
      .toHaveAttribute("data-state", "checked");
  });
});
