import { DepartmentSettings } from "@/pages/DepartmentPage/components/DepartmentSettings";
import {
  getDepartmentAdminsApi,
  getDepartmentApi,
  getDepartmentAssignableRolesApi,
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
      short_name: "R&D",
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
      <DepartmentSettings
        dept={dept}
        tree={[{ ...dept, id: 1, dept_id: "BS@root", name: "Root", parent_id: null, path: "/1/", children: [dept] }]}
        onChanged={vi.fn()}
      />,
    );

    const input = await screen.findByDisplayValue("Engineering");
    fireEvent.change(input, { target: { value: "Engineering 2" } });
    fireEvent.click(screen.getByRole("button", { name: "save" }));

    await waitFor(() => {
      expect(mockedUpdateDepartmentApi).toHaveBeenCalledTimes(1);
    });
    expect(mockedUpdateDepartmentApi).toHaveBeenCalledWith("BS@dept", { name: "Engineering 2" });
  });

  it("submits a normalized short name without unrelated fields", async () => {
    render(
      <DepartmentSettings dept={dept} tree={[dept]} onChanged={vi.fn()} />,
    );

    const input = await screen.findByDisplayValue("R&D");
    fireEvent.change(input, { target: { value: "  Eng  " } });
    fireEvent.click(screen.getByRole("button", { name: "save" }));

    await waitFor(() => expect(mockedUpdateDepartmentApi).toHaveBeenCalledTimes(1));
    expect(mockedUpdateDepartmentApi).toHaveBeenCalledWith("BS@dept", {
      short_name: "Eng",
    });
  });

  it("submits null when the saved short name is cleared", async () => {
    render(
      <DepartmentSettings dept={dept} tree={[dept]} onChanged={vi.fn()} />,
    );

    const input = await screen.findByDisplayValue("R&D");
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "save" }));

    await waitFor(() => expect(mockedUpdateDepartmentApi).toHaveBeenCalledTimes(1));
    expect(mockedUpdateDepartmentApi).toHaveBeenCalledWith("BS@dept", {
      short_name: null,
    });
  });

  it("does not submit when settings are unchanged", async () => {
    render(
      <DepartmentSettings dept={dept} tree={[dept]} onChanged={vi.fn()} />,
    );

    await screen.findByDisplayValue("R&D");
    fireEvent.click(screen.getByRole("button", { name: "save" }));

    await waitFor(() => expect(mockedGetDepartmentApi).toHaveBeenCalledTimes(1));
    expect(mockedUpdateDepartmentApi).not.toHaveBeenCalled();
  });

  it("keeps synced department name disabled while allowing short name edits", async () => {
    render(
      <DepartmentSettings
        dept={{ ...dept, source: "wecom" }}
        tree={[{ ...dept, source: "wecom" }]}
        onChanged={vi.fn()}
      />,
    );

    expect(await screen.findByDisplayValue("Engineering")).toBeDisabled();
    expect(screen.getByDisplayValue("R&D")).not.toBeDisabled();
  });

  it("keeps archived department name and short name disabled", async () => {
    render(
      <DepartmentSettings
        dept={{ ...dept, status: "archived" }}
        tree={[{ ...dept, status: "archived" }]}
        onChanged={vi.fn()}
      />,
    );

    expect(await screen.findByDisplayValue("Engineering")).toBeDisabled();
    expect(screen.getByDisplayValue("R&D")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "save" })).not.toBeInTheDocument();
  });
});
