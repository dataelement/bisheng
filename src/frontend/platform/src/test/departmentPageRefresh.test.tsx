import userEvent from "@testing-library/user-event";
import DepartmentPage from "@/pages/DepartmentPage";
import { createDepartmentApi, getDepartmentChildrenApi, getDepartmentPathTreeApi } from "@/controllers/API/department";
import { fireEvent, render, screen, waitFor, within } from "@/test/test-utils";
import type { DepartmentTreeNode } from "@/types/api/department";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// F038: DepartmentPage lazy-loads the tree (root layer via getDepartmentChildrenApi).
vi.mock("@/controllers/API/department", () => ({
  createDepartmentApi: vi.fn(),
  getDepartmentChildrenApi: vi.fn(),
  getDepartmentPathTreeApi: vi.fn(() => Promise.resolve({ roots: [], total_matches: 0, truncated: false })),
  searchDepartmentsApi: vi.fn(() => Promise.resolve({ roots: [], total_matches: 0, truncated: false })),
}));

vi.mock("@/controllers/request", async (importOriginal) => ({
  ...await importOriginal<typeof import('@/controllers/request')>(),
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => promise),
  showApiError: vi.fn(),
}));

vi.mock("@/pages/DepartmentPage/components/MemberTable", () => ({
  MemberTable: ({ membersRefreshSignal, toolbarActions }: { membersRefreshSignal: number; toolbarActions: ReactNode }) => (
    <><div data-testid="members-refresh-signal">{membersRefreshSignal}</div>{toolbarActions}</>
  )
}));

vi.mock("@/pages/DepartmentPage/components/DepartmentSettingsDialog", () => ({
  DepartmentSettingsDialog: ({ onChanged }: { onChanged: () => void }) => (
    <button type="button" onClick={() => onChanged()}>
      save department settings
    </button>
  ),
}));

vi.mock("@/components/bs-comp/department/TreeDepartmentSelect", () => ({
  TreeDepartmentSelect: ({ onChange }: { onChange: (id: number) => void }) => (
    <button type="button" onClick={() => onChange(3)}>Choose Team as parent</button>
  ),
}));

vi.mock("@/components/bs-comp/selectComponent/DepartmentUsersSelect", () => ({
  default: () => null,
}));

const dept: DepartmentTreeNode = {
  id: 1,
  dept_id: "BS@root",
  name: "Root",
  parent_id: null,
  path: "/1/",
  sort_order: 0,
  source: "local",
  status: "active",
  is_tenant_root: false,
  mounted_tenant_id: null,
  has_children: false,
  children: [],
};

const mockedChildren = vi.mocked(getDepartmentChildrenApi);

describe("DepartmentPage tree and member refresh", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedChildren.mockReset();
    mockedChildren.mockImplementation((parentId: number | null) =>
      Promise.resolve(parentId == null ? [dept] : [])
    );
  });

  it("refreshes the member table after department settings change", async () => {
    render(<DepartmentPage />);

    expect(await screen.findByTestId("members-refresh-signal")).toHaveTextContent("0");
    await userEvent.click(screen.getByRole("button", { name: "bs:department.settings" }));
    fireEvent.click(screen.getByRole("button", { name: "save department settings" }));

    await waitFor(() => {
      expect(screen.getByTestId("members-refresh-signal")).toHaveTextContent("1");
    });
    // The root layer is refetched on change (the lazy equivalent of the old
    // full-tree refresh): once on mount, again after the settings change.
    expect(mockedChildren.mock.calls.filter(([parentId]) => parentId == null).length).toBeGreaterThanOrEqual(2);
  });

  it.each(["row", "toolbar"])("reveals a created subdepartment from the %s without a refresh", async (entry) => {
    const root = { ...dept, has_children: true };
    const division = { ...dept, id: 2, dept_id: "BS@division", name: "Division", parent_id: 1, path: "/1/2/", has_children: true };
    const team = { ...dept, id: 3, dept_id: "BS@team", name: "Team", parent_id: 2, path: "/1/2/3/" };
    const child = { ...dept, id: 4, dept_id: "BS@new", name: "New subdepartment", parent_id: 3, path: "/1/2/3/4/" };
    let created = false;
    mockedChildren.mockImplementation(async (parentId) => {
      if (parentId === null) return [root];
      if (parentId === root.id) return [division];
      if (parentId === division.id) return [{ ...team, has_children: created }];
      return parentId === team.id && created ? [child] : [];
    });
    vi.mocked(createDepartmentApi).mockImplementationOnce(async () => {
      created = true;
      return child;
    });
    vi.mocked(getDepartmentPathTreeApi).mockResolvedValueOnce({
      roots: [{ ...root, children: [{ ...division, children: [{ ...team, has_children: true, children: [child] }] }] }],
      total_matches: 1,
      truncated: false,
    });

    const user = userEvent.setup();
    render(<DepartmentPage />);
    const divisionRow = (await screen.findByRole("button", { name: "Division" })).closest<HTMLElement>("[data-tree-row]")!;
    if (entry === "row") {
      await user.click(within(divisionRow).getByRole("button", { expanded: false }));
      const teamRow = (await screen.findByRole("button", { name: "Team" })).closest<HTMLElement>("[data-tree-row]")!;
      await user.click(within(teamRow).getByRole("button", { name: "bs:organization.createChildDepartmentFor" }));
    } else {
      await user.click(screen.getByRole("button", { name: "bs:department.create" }));
      await user.click(screen.getByRole("button", { name: "Choose Team as parent" }));
    }
    await user.type(screen.getByPlaceholderText("bs:department.nameRequired"), child.name);
    await user.click(screen.getByRole("button", { name: "confirmButton" }));

    expect(createDepartmentApi).toHaveBeenCalledWith(expect.objectContaining({ name: child.name, parent_id: team.id }));
    expect(await screen.findByRole("button", { name: "New subdepartment" })).toBeVisible();
    const teamRow = screen.getByRole("button", { name: "Team" }).closest<HTMLElement>("[data-tree-row]")!;
    expect(within(teamRow).getByRole("button", { expanded: true })).toBeVisible();
    expect(screen.getByRole("button", { name: "Root" })).toHaveAttribute("aria-current", "true");
  });

  it("leaves an empty arrow slot for a known leaf department", async () => {
    render(<DepartmentPage />);

    const label = await screen.findByRole("button", { name: "Root" });
    const arrow = label.closest("[data-tree-row]")?.firstElementChild;
    expect(arrow).toHaveAttribute("aria-hidden", "true");
    expect(arrow?.querySelector("svg")).toBeNull();
    expect(screen.queryByRole("button", { name: "bs:organization.expandDepartment" })).toBeNull();
    expect(mockedChildren.mock.calls.every(([parentId]) => parentId === null)).toBe(true);
  });

  it("removes the root disclosure when its child request returns no rows", async () => {
    mockedChildren.mockResolvedValueOnce([{ ...dept, has_children: true }]).mockResolvedValue([]);
    render(<DepartmentPage />);

    await waitFor(() => expect(mockedChildren).toHaveBeenCalledWith(dept.id, false));
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    expect(screen.queryByRole("button", { name: "bs:organization.collapseDepartment" })).toBeNull();
    expect(screen.getByRole("button", { name: "Root" })).toHaveAttribute("aria-current", "true");
  });

  it("retries a failed branch in place without changing the current department", async () => {
    const branch = { ...dept, has_children: true };
    const child = { ...dept, id: 2, dept_id: "BS@child", name: "Child", parent_id: dept.id, path: "/1/2/" };
    mockedChildren.mockResolvedValueOnce([branch]).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce([child]);
    render(<DepartmentPage />);

    const retry = await screen.findByRole("button", { name: "bs:organization.retry" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Root" })).toHaveAttribute("aria-current", "true"));
    fireEvent.click(retry);
    expect(await screen.findByRole("button", { name: "Child" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Root" })).toHaveAttribute("aria-current", "true");
    expect(mockedChildren).toHaveBeenLastCalledWith(dept.id, false);
  });

  it("omits the expand control for a leaf and removes it when a branch loads empty", async () => {
    const root = { ...dept, has_children: true };
    const leaf = { ...dept, id: 2, dept_id: "BS@leaf", name: "Leaf", parent_id: root.id, path: "/1/2/" };
    const emptyBranch = {
      ...leaf, id: 3, dept_id: "BS@empty", name: "Empty branch", path: "/1/3/", has_children: true,
    };
    mockedChildren.mockImplementation(async (parentId) => {
      if (parentId === null) return [root];
      if (parentId === root.id) return [leaf, emptyBranch];
      return [];
    });
    render(<DepartmentPage />);

    const leafRow = (await screen.findByRole("button", { name: "Leaf" })).closest<HTMLElement>("[data-tree-row]")!;
    expect(leafRow.querySelector("[data-tree-disclosure]")).toBeNull();
    const branchRow = screen.getByRole("button", { name: "Empty branch" }).closest<HTMLElement>("[data-tree-row]")!;
    await userEvent.click(within(branchRow).getByRole("button", { expanded: false }));
    await waitFor(() => expect(branchRow.querySelector("[data-tree-disclosure]")).toBeNull());
    expect(mockedChildren).toHaveBeenCalledWith(emptyBranch.id, false);
    expect(within(branchRow).getByRole("button", { name: "Empty branch" })).toBeVisible();
  });
});
