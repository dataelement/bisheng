import Departments from "@/pages/SystemPage/components/Departments";
import { getDepartmentTreeApi } from "@/controllers/API/department";
import { fireEvent, render, screen, waitFor } from "@/test/test-utils";
import type { DepartmentTreeNode } from "@/types/api/department";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/controllers/API/department", () => ({
  getDepartmentTreeApi: vi.fn(),
}));

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => promise),
}));

vi.mock("@/pages/DepartmentPage/components/DepartmentTree", () => ({
  DepartmentTree: () => <div data-testid="department-tree" />,
}));

vi.mock("@/pages/DepartmentPage/components/MemberTable", () => ({
  MemberTable: ({
    deptName,
    isArchived,
  }: {
    deptName: string;
    isArchived?: boolean;
  }) => (
    <button type="button" disabled={isArchived} data-testid="create-local-user">
      {deptName}: bs:department.createLocalUser
    </button>
  ),
}));

vi.mock("@/pages/DepartmentPage/components/DepartmentSettings", () => ({
  DepartmentSettings: ({
    dept,
    onChanged,
  }: {
    dept: DepartmentTreeNode;
    onChanged: (removedDeptId?: string) => void;
  }) => (
    <div>
      <div data-testid="settings-dept-name">{dept.name}</div>
      <button type="button" onClick={() => onChanged(dept.dept_id)}>
        purge selected department
      </button>
    </div>
  ),
}));

vi.mock("@/pages/DepartmentPage/components/CreateDepartmentDialog", () => ({
  CreateDepartmentDialog: () => null,
}));

vi.mock("@/pages/DepartmentPage/components/DepartmentTrafficControl", () => ({
  DepartmentTrafficControl: () => null,
}));

const archivedDept: DepartmentTreeNode = {
  id: 1,
  dept_id: "BS@archived",
  name: "Archived Dept",
  parent_id: null,
  path: "1/",
  sort_order: 0,
  source: "local",
  status: "archived",
  member_count: 0,
  children: [],
};

const activeDept: DepartmentTreeNode = {
  id: 2,
  dept_id: "BS@active",
  name: "Active Dept",
  parent_id: null,
  path: "2/",
  sort_order: 0,
  source: "local",
  status: "active",
  member_count: 0,
  children: [],
};

const mockedGetDepartmentTreeApi = vi.mocked(getDepartmentTreeApi);

describe("System departments archived and deleted states", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetDepartmentTreeApi.mockResolvedValue([archivedDept]);
  });

  it("disables local member creation for archived departments", async () => {
    render(<Departments />);

    expect(await screen.findByTestId("create-local-user")).toBeDisabled();
  });

  it("switches away from a permanently deleted selected department", async () => {
    const user = userEvent.setup();
    mockedGetDepartmentTreeApi
      .mockResolvedValueOnce([archivedDept])
      .mockResolvedValueOnce([activeDept]);

    render(<Departments />);

    await screen.findByText("Archived Dept");
    await user.click(screen.getByRole("tab", { name: "bs:department.settings" }));
    expect(await screen.findByTestId("settings-dept-name")).toHaveTextContent("Archived Dept");

    fireEvent.click(screen.getByRole("button", { name: "purge selected department" }));

    await waitFor(() => {
      expect(screen.getByTestId("settings-dept-name")).toHaveTextContent("Active Dept");
    });
    expect(screen.queryByText("Archived Dept")).not.toBeInTheDocument();
  });
});
