import DepartmentPage from "@/pages/DepartmentPage";
import {
  getDepartmentApi,
  getDepartmentChildrenApi,
  getDepartmentPathTreeApi,
  searchDepartmentsApi,
} from "@/controllers/API/department";
import { fireEvent, render, screen, waitFor } from "@/test/test-utils";
import type { DepartmentTreeNode } from "@/types/api/department";
import { beforeEach, describe, expect, it, vi } from "vitest";

// F038: DepartmentPage lazy-loads the tree (root layer via getDepartmentChildrenApi).
vi.mock("@/controllers/API/department", () => ({
  getDepartmentChildrenApi: vi.fn(),
  getDepartmentApi: vi.fn(),
  getDepartmentPathTreeApi: vi.fn(() => Promise.resolve({ roots: [], total_matches: 0, truncated: false })),
  searchDepartmentsApi: vi.fn(() => Promise.resolve({ roots: [], total_matches: 0, truncated: false })),
}));

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => promise),
}));

// Keep the real useLazyDepartmentTree hook but stub the visual tree (SVG import).
vi.mock("@/components/bs-comp/department", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/bs-comp/department")>();
  return { ...actual, LazyDepartmentTree: () => <div data-testid="lazy-tree" /> };
});

vi.mock("@/components/bs-ui/tabs", () => ({
  Tabs: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TabsContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TabsList: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TabsTrigger: ({ children }: { children: React.ReactNode }) => <button type="button">{children}</button>,
}));

vi.mock("@/pages/DepartmentPage/components/MemberTable", () => ({
  MemberTable: ({ membersRefreshSignal }: { membersRefreshSignal: number }) => (
    <div data-testid="members-refresh-signal">{membersRefreshSignal}</div>
  ),
}));

vi.mock("@/pages/DepartmentPage/components/DepartmentSettings", () => ({
  DepartmentSettings: ({ onChanged }: { onChanged: () => void }) => (
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
    vi.mocked(getDepartmentApi).mockResolvedValue({ id: 1, dept_id: "BS@root" } as any);
  });

  it("refreshes the member table after department settings change", async () => {
    render(<DepartmentPage />);

    await screen.findByText("Root");
    expect(screen.getByTestId("members-refresh-signal")).toHaveTextContent("0");

    fireEvent.click(screen.getByRole("button", { name: "save department settings" }));

    await waitFor(() => {
      expect(screen.getByTestId("members-refresh-signal")).toHaveTextContent("1");
    });
    // The root layer is refetched on change (the lazy equivalent of the old
    // full-tree refresh): once on mount, again after the settings change.
    expect(mockedChildren.mock.calls.filter(([parentId]) => parentId == null).length).toBeGreaterThanOrEqual(2);
  });
});
