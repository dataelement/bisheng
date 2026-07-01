import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import {
  getResourceGrantDepartmentChildren,
  searchResourceGrantDepartments,
} from "~/api/permission";
import type { SelectedSubject } from "~/api/permission";
import { SubjectSearchDepartment } from "./SubjectSearchDepartment";

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

// F038: the client picker is now a lazy tree fed by the resource-scoped grant
// endpoints (children / search). No full-tree load.
jest.mock("~/api/permission", () => ({
  getResourceGrantDepartmentChildren: jest.fn(),
  searchResourceGrantDepartments: jest.fn(),
}));

const mockedChildren = jest.mocked(getResourceGrantDepartmentChildren);
const mockedSearch = jest.mocked(searchResourceGrantDepartments);

const node = (
  id: number,
  name: string,
  parent_id: number | null,
  path: string,
  has_children: boolean,
  matched = false,
) => ({
  id,
  dept_id: `dept-${id}`,
  name,
  parent_id,
  path,
  has_children,
  matched,
  children: [] as any[],
});

const emptySearch = { roots: [], total_matches: 0, truncated: false };

describe("SubjectSearchDepartment (lazy, F038 decision 9/10)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Root layer = 全集团 (has children); search returns its pruned subtree.
    mockedChildren.mockResolvedValue([node(1, "全集团", null, "/1/", true)] as any);
    mockedSearch.mockResolvedValue(emptySearch as any);
  });

  it("lazy-loads the grant root layer via the resource-scoped children endpoint", async () => {
    render(
      <SubjectSearchDepartment
        value={[]}
        onChange={jest.fn()}
        resourceType="workflow"
        resourceId="wf-1"
        includeChildren
      />,
    );

    await waitFor(() => {
      expect(mockedChildren).toHaveBeenCalledWith("workflow", "wf-1", null, {
        signal: expect.any(AbortSignal),
      });
    });
    expect(await screen.findByText("全集团")).toBeInTheDocument();
  });

  it("shows descendants as checked + disabled (implicit) when an ancestor grant includes children — decision 9 (path-based)", async () => {
    mockedSearch.mockResolvedValue({
      roots: [
        { ...node(1, "全集团", null, "/1/", true), children: [node(2, "子部门", 1, "/1/2/", false, true)] },
      ],
      total_matches: 1,
      truncated: false,
    } as any);

    const value: SelectedSubject[] = [
      { type: "department", id: 1, name: "全集团", include_children: true },
    ];

    render(
      <SubjectSearchDepartment
        value={value}
        onChange={jest.fn()}
        resourceType="workflow"
        resourceId="wf-1"
        includeChildren
      />,
    );

    // Root load primes the ancestor's path so implicit selection resolves.
    await screen.findByText("全集团");
    fireEvent.change(screen.getByPlaceholderText("com_permission.search_department"), {
      target: { value: "子部门" },
    });

    const childLabel = await screen.findByText("子部门");
    const childCheckbox = within(childLabel.parentElement as HTMLElement).getByRole("checkbox");
    expect(childCheckbox).toHaveAttribute("data-state", "checked");
    expect(childCheckbox).toBeDisabled();
  });

  it("summarizes only the explicit picks, never the materialized subtree — decision 10", async () => {
    const onSelectionSummaryChange = jest.fn();

    render(
      <SubjectSearchDepartment
        value={[{ type: "department", id: 1, name: "全集团", include_children: true }]}
        onChange={jest.fn()}
        resourceType="workflow"
        resourceId="wf-1"
        includeChildren
        onSelectionSummaryChange={onSelectionSummaryChange}
      />,
    );

    await waitFor(() => {
      expect(onSelectionSummaryChange).toHaveBeenLastCalledWith([
        { type: "department", id: 1, name: "全集团", include_children: true },
      ]);
    });
  });

  it("shows already granted departments as disabled and unchecked without selecting them", async () => {
    render(
      <SubjectSearchDepartment
        value={[]}
        onChange={jest.fn()}
        resourceType="workflow"
        resourceId="wf-1"
        includeChildren
        disabledIds={[1]}
      />,
    );

    const departmentLabel = await screen.findByText("全集团");
    const checkbox = within(departmentLabel.parentElement as HTMLElement).getByRole("checkbox");

    expect(checkbox).toHaveAttribute("data-state", "unchecked");
    expect(checkbox).toBeDisabled();
    expect(screen.getByText("com_permission.already_granted")).toBeInTheDocument();
  });

  it("adds a department carrying the current include-children flag when toggled on", async () => {
    const onChange = jest.fn();

    render(
      <SubjectSearchDepartment
        value={[]}
        onChange={onChange}
        resourceType="workflow"
        resourceId="wf-1"
        includeChildren
      />,
    );

    fireEvent.click(await screen.findByText("全集团"));

    expect(onChange).toHaveBeenCalledWith([
      { type: "department", id: 1, name: "全集团", include_children: true },
    ]);
  });
});
