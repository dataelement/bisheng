import Departments from "@/pages/SystemPage/components/Departments";
import {
  getDepartmentApi,
  getDepartmentChildrenApi,
  getDepartmentPathTreeApi,
  searchDepartmentsApi,
} from "@/controllers/API/department";
import { fireEvent, render, screen, waitFor } from "@/test/test-utils";
import type { DepartmentTreeNode } from "@/types/api/department";
import { beforeEach, describe, expect, it, vi } from "vitest";

// F038: Departments now lazy-loads the tree (root layer via getDepartmentChildrenApi,
// children on expand, locate via getDepartmentApi → reveal) instead of one /tree call.
vi.mock("@/controllers/API/department", () => ({
  getDepartmentChildrenApi: vi.fn(),
  getDepartmentApi: vi.fn(),
  getDepartmentPathTreeApi: vi.fn(() => Promise.resolve({ roots: [], total_matches: 0, truncated: false })),
  searchDepartmentsApi: vi.fn(() => Promise.resolve({ roots: [], total_matches: 0, truncated: false })),
}));

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => promise),
}));

// Keep the real useLazyDepartmentTree hook (drives selection/auto-select) but stub
// the visual tree — its SearchInput imports an SVG that jsdom can't render.
vi.mock("@/components/bs-comp/department", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/bs-comp/department")>();
  return { ...actual, LazyDepartmentTree: () => <div data-testid="lazy-tree" /> };
});

vi.mock("@/pages/DepartmentPage/components/MemberTable", () => ({
  MemberTable: ({
    deptName,
    isArchived,
    dept,
    onChanged,
  }: {
    deptName: string;
    isArchived?: boolean;
    dept?: DepartmentTreeNode | null;
    onChanged?: (removedDeptId?: string) => void;
  }) => (
    <div>
      <button type="button" disabled={isArchived} data-testid="create-local-user">
        {deptName}: bs:department.createLocalUser
      </button>
      <div data-testid="member-table-context">{dept?.dept_id ?? "none"}</div>
      {/* Stand-in for "the selected dept was removed" (delete/purge). */}
      <button type="button" data-testid="purge-selected" onClick={() => onChanged?.(dept?.dept_id)}>
        purge
      </button>
    </div>
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
  path: "/1/",
  sort_order: 0,
  source: "local",
  status: "archived",
  is_tenant_root: false,
  mounted_tenant_id: null,
  has_children: false,
  children: [],
};

const activeDept: DepartmentTreeNode = {
  id: 2,
  dept_id: "BS@active",
  name: "Active Dept",
  parent_id: null,
  path: "/2/",
  sort_order: 0,
  source: "local",
  status: "active",
  is_tenant_root: false,
  mounted_tenant_id: null,
  has_children: false,
  children: [],
};

const mockedChildren = vi.mocked(getDepartmentChildrenApi);
const mockedGetDepartment = vi.mocked(getDepartmentApi);

/** Drive the root layer; children of any node are empty here. */
let rootLayer: DepartmentTreeNode[] = [];
function setRootLayer(layer: DepartmentTreeNode[]) {
  rootLayer = layer;
}

describe("System departments archived and deleted states", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setRootLayer([archivedDept]);
    mockedChildren.mockImplementation((parentId: number | null) =>
      Promise.resolve(parentId == null ? rootLayer : [])
    );
    mockedGetDepartment.mockResolvedValue({ id: 1, dept_id: "BS@archived" } as any);
  });

  it("disables local member creation for archived departments", async () => {
    render(<Departments />);

    expect(await screen.findByTestId("create-local-user")).toBeDisabled();
  });

  it("passes the selected department context into the member table", async () => {
    render(<Departments />);

    await waitFor(() => {
      expect(screen.getByTestId("member-table-context")).toHaveTextContent("BS@archived");
    });
  });

  it("switches away from a permanently deleted selected department", async () => {
    render(<Departments />);

    await waitFor(() => {
      expect(screen.getByTestId("member-table-context")).toHaveTextContent("BS@archived");
    });

    // After purge the refreshed root layer no longer contains the archived dept;
    // the page must drop the stale selection and fall back to the fresh first root.
    setRootLayer([activeDept]);
    fireEvent.click(screen.getByTestId("purge-selected"));

    await waitFor(() => {
      expect(screen.getByTestId("member-table-context")).toHaveTextContent("BS@active");
    });
    expect(screen.queryByText("Archived Dept")).not.toBeInTheDocument();
  });
});
