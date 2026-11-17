import userEvent from "@testing-library/user-event";
import DepartmentPage from "@/pages/DepartmentPage";
import { getDepartmentChildrenApi } from "@/controllers/API/department";
import { fireEvent, render, screen, waitFor } from "@/test/test-utils";
import type { DepartmentTreeNode } from "@/types/api/department";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// F038: DepartmentPage lazy-loads the tree (root layer via getDepartmentChildrenApi).
vi.mock("@/controllers/API/department", () => ({
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

vi.mock("@/pages/DepartmentPage/components/CreateDepartmentDialog", () => ({
  CreateDepartmentDialog: () => null,
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

describe("DepartmentPage member refresh", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

  it("retries a failed branch in place without changing the current department", async () => {
    const branch = { ...dept, has_children: true };
    const child = { ...dept, id: 2, dept_id: "BS@child", name: "Child", parent_id: dept.id, path: "/1/2/" };
    mockedChildren.mockResolvedValueOnce([branch]).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce([child]);
    render(<DepartmentPage />);

    const retry = await screen.findByRole("button", { name: "bs:organization.retry" });
    expect(screen.getByRole("button", { name: "Root" })).toHaveAttribute("aria-current", "true");
    fireEvent.click(retry);
    expect(await screen.findByRole("button", { name: "Child" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Root" })).toHaveAttribute("aria-current", "true");
    expect(mockedChildren).toHaveBeenLastCalledWith(dept.id, false);
  });
});
