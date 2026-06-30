import { DepartmentSettings } from "@/pages/DepartmentPage/components/DepartmentSettings";
import {
  getDepartmentAdminsApi,
  getDepartmentApi,
  getDepartmentAssignableRolesApi,
  getDepartmentChildrenApi,
  getDepartmentPathTreeApi,
  moveDepartmentApi,
  updateDepartmentApi,
} from "@/controllers/API/department";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { fireEvent, render, screen, waitFor } from "@/test/test-utils";
import type { DepartmentTreeNode } from "@/types/api/department";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockT = (key: string) => key;

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: mockT }),
}));

vi.mock("@/controllers/API/department", () => ({
  deleteDepartmentApi: vi.fn(),
  getDepartmentAdminsApi: vi.fn(),
  getDepartmentApi: vi.fn(),
  getDepartmentAssignableRolesApi: vi.fn(),
  // F038: DepartmentSettings now resolves root-layer membership + the read-only
  // parent name lazily; default them to empty so the effect is a no-op here.
  getDepartmentChildrenApi: vi.fn(() => Promise.resolve([])),
  getDepartmentPathTreeApi: vi.fn(() => Promise.resolve({ roots: [], total_matches: 0, truncated: false })),
  moveDepartmentApi: vi.fn(),
  purgeDepartmentApi: vi.fn(),
  restoreDepartmentApi: vi.fn(),
  updateDepartmentApi: vi.fn(),
}));

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => promise),
}));

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  toast: vi.fn(),
}));

vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: vi.fn(),
}));

vi.mock("@/components/bs-comp/department/TreeDepartmentSelect", () => ({
  TreeDepartmentSelect: () => <div data-testid="tree-select" />,
}));

vi.mock("@/components/bs-comp/selectComponent/DepartmentUsersSelect", () => ({
  __esModule: true,
  default: () => <div data-testid="admin-select" />,
}));

vi.mock("@/components/bs-ui/select/multi", () => ({
  __esModule: true,
  default: () => <div data-testid="roles-select" />,
}));

const mockedGetDepartmentAdminsApi = vi.mocked(getDepartmentAdminsApi);
const mockedGetDepartmentApi = vi.mocked(getDepartmentApi);
const mockedGetDepartmentAssignableRolesApi = vi.mocked(getDepartmentAssignableRolesApi);
const mockedMoveDepartmentApi = vi.mocked(moveDepartmentApi);
const mockedUpdateDepartmentApi = vi.mocked(updateDepartmentApi);
const mockedGetDepartmentChildrenApi = vi.mocked(getDepartmentChildrenApi);
const mockedGetDepartmentPathTreeApi = vi.mocked(getDepartmentPathTreeApi);
const mockedCapture = vi.mocked(captureAndAlertRequestErrorHoc);

const dept: DepartmentTreeNode = {
  id: 2,
  dept_id: "BS@dept",
  name: "Engineering",
  parent_id: 1,
  path: "/1/2/",
  sort_order: 0,
  source: "local",
  status: "active",
  is_tenant_root: false,
  mounted_tenant_id: null,
  children: [],
};

describe("DepartmentSettings payload", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetDepartmentAdminsApi.mockResolvedValue([{ user_id: 7, user_name: "alice" }] as any);
    mockedGetDepartmentApi.mockResolvedValue({
      id: 2,
      dept_id: "BS@dept",
      name: "Engineering",
      parent_id: 1,
      path: "/1/2/",
      sort_order: 0,
      source: "local",
      status: "active",
      default_role_ids: [11],
      member_count: 0,
    } as any);
    mockedGetDepartmentAssignableRolesApi.mockResolvedValue([{ id: 11, role_name: "viewer" }] as any);
    mockedMoveDepartmentApi.mockResolvedValue({} as any);
    mockedUpdateDepartmentApi.mockResolvedValue({} as any);
    mockedCapture.mockImplementation((promise: Promise<unknown>) => promise as any);
  });

  it("does not submit admin_user_ids when only the name changes", async () => {
    render(
      <DepartmentSettings dept={dept} onChanged={vi.fn()} />,
    );

    const input = await screen.findByDisplayValue("Engineering");
    fireEvent.change(input, { target: { value: "Engineering 2" } });
    fireEvent.click(screen.getByRole("button", { name: "save" }));

    await waitFor(() => {
      expect(mockedUpdateDepartmentApi).toHaveBeenCalledTimes(1);
    });
    expect(mockedUpdateDepartmentApi).toHaveBeenCalledWith("BS@dept", { name: "Engineering 2" });
  });

  // A sub-tenant admin opens the settings of their OWN tenant-root dept. The
  // visible root layer (getDepartmentChildrenApi(null)) is that very dept, so its
  // parent (the global root) is OUTSIDE their scope — fetching the parent's
  // path-tree would 21009. The page must not call it.
  it("does not fetch the parent path-tree when the dept is the top of the viewer's visible tree", async () => {
    mockedGetDepartmentChildrenApi.mockResolvedValue([{ ...dept }] as any);

    render(<DepartmentSettings dept={dept} onChanged={vi.fn()} />);

    await screen.findByDisplayValue("Engineering");
    await waitFor(() => expect(mockedGetDepartmentChildrenApi).toHaveBeenCalled());

    expect(mockedGetDepartmentPathTreeApi).not.toHaveBeenCalled();
  });

  // A tenant-root dept is a top-level entity in the management UI: its parent is
  // the system root — out of scope for a tenant admin, and not a meaningful
  // "上级部门" for anyone (incl. a super admin whose visible root layer is the
  // GLOBAL root, which excludes this sub-tenant). It must be treated as a root:
  // the parent field is hidden and no parent path-tree is fetched, role-agnostic.
  it("treats a tenant-root dept as a root and never fetches its out-of-scope parent", async () => {
    const tenantRoot = { ...dept, is_tenant_root: true };
    // Super-admin-style root layer: the global root, NOT this sub-tenant.
    mockedGetDepartmentChildrenApi.mockResolvedValue([
      { ...dept, id: 1, name: "Root", parent_id: null, path: "/1/" },
    ] as any);
    mockedGetDepartmentApi.mockResolvedValue({
      ...dept,
      default_role_ids: [11],
      is_tenant_root: true,
    } as any);

    render(<DepartmentSettings dept={tenantRoot} onChanged={vi.fn()} />);

    await screen.findByDisplayValue("Engineering");
    await Promise.resolve();
    expect(mockedGetDepartmentPathTreeApi).not.toHaveBeenCalled();
    // The read-only "上级部门" field is hidden for a root dept.
    expect(screen.queryByText("bs:department.parentDept")).not.toBeInTheDocument();
  });

  // A dept nested below the viewer's visible root: its parent IS in scope, so the
  // read-only parent name is resolved via a parent path-tree fetch.
  it("fetches the parent path-tree for the read-only parent name when the dept is nested in the visible tree", async () => {
    mockedGetDepartmentChildrenApi.mockResolvedValue([
      { ...dept, id: 99, dept_id: "BS@root", name: "Root", parent_id: null, path: "/99/" },
    ] as any);
    mockedGetDepartmentPathTreeApi.mockResolvedValue({
      roots: [{ ...dept, id: 1, name: "Parent", parent_id: null, path: "/1/", children: [] }],
      total_matches: 1,
      truncated: false,
    } as any);

    render(<DepartmentSettings dept={dept} onChanged={vi.fn()} />);

    await screen.findByDisplayValue("Engineering");
    await waitFor(() => expect(mockedGetDepartmentPathTreeApi).toHaveBeenCalledWith(1));
  });
});
