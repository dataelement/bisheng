import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { GrantDepartmentNode } from "~/api/permission";
import {
  isDepartmentPathCovered,
  SubjectSearchDepartment,
} from "./SubjectSearchDepartment";

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

afterEach(() => {
  jest.useRealTimers();
});

const parent: GrantDepartmentNode = {
  id: 10,
  dept_id: "10",
  name: "Parent",
  parent_id: null,
  path: "/10/",
  has_children: true,
};

const child: GrantDepartmentNode = {
  id: 11,
  dept_id: "11",
  name: "Child",
  parent_id: 10,
  path: "/10/11/",
  has_children: false,
};

function renderPicker({
  disabledIds = [10],
  disabledSubtreeRootIds = [10],
  searchResult = { roots: [child], total_matches: 1, truncated: false },
}: {
  disabledIds?: number[];
  disabledSubtreeRootIds?: number[];
  searchResult?: { roots: GrantDepartmentNode[]; total_matches: number; truncated: boolean };
} = {}) {
  const onChange = jest.fn();
  const departmentChildrenApi = jest.fn(async (
    _resourceType: string,
    _resourceId: string,
    parentId: number | null,
  ) => (parentId === null ? [parent] : [child]));
  const departmentSearchApi = jest.fn(async () => searchResult);

  render(
    <SubjectSearchDepartment
      value={[]}
      onChange={onChange}
      resourceType="knowledge_space"
      resourceId="space-1"
      includeChildren
      disabledIds={disabledIds}
      disabledSubtreeRootIds={disabledSubtreeRootIds}
      departmentChildrenApi={departmentChildrenApi}
      departmentSearchApi={departmentSearchApi}
    />,
  );

  return { onChange, departmentSearchApi };
}

describe("SubjectSearchDepartment existing subtree grants", () => {
  it("disables descendants loaded by browsing when an existing parent grant includes children", async () => {
    const { onChange } = renderPicker();

    await screen.findByText("Parent");
    fireEvent.click(screen.getByRole("button", { name: "Expand department" }));
    await screen.findByText("Child");

    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(2);
    expect(checkboxes[0]).toBeChecked();
    expect(checkboxes[0]).toBeDisabled();
    expect(checkboxes[1]).toBeChecked();
    expect(checkboxes[1]).toBeDisabled();
    fireEvent.click(screen.getByText("Child"));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("applies the same disabled subtree state to search results", async () => {
    jest.useFakeTimers();
    const { departmentSearchApi } = renderPicker();
    await screen.findByText("Parent");

    fireEvent.change(screen.getByPlaceholderText("com_permission.search_department"), {
      target: { value: "Child" },
    });
    await act(async () => {
      jest.advanceTimersByTime(300);
    });

    await waitFor(() => expect(departmentSearchApi).toHaveBeenCalled());
    expect(await screen.findByText("Child")).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(screen.getByRole("checkbox")).toBeDisabled();
  });

  it("does not disable descendants for an exact-only department grant", async () => {
    renderPicker({ disabledSubtreeRootIds: [] });

    await screen.findByText("Parent");
    fireEvent.click(screen.getByRole("button", { name: "Expand department" }));
    await screen.findByText("Child");

    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes[0]).toBeDisabled();
    expect(checkboxes[1]).not.toBeChecked();
    expect(checkboxes[1]).not.toBeDisabled();
  });

  it("matches department path segments instead of numeric prefixes", () => {
    expect(isDepartmentPathCovered("/1/12/", new Set([1]))).toBe(true);
    expect(isDepartmentPathCovered("/11/12/", new Set([1]))).toBe(false);
  });
});
