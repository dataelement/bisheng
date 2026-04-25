import DepartmentPage from "@/pages/DepartmentPage";
import { getDepartmentTreeApi } from "@/controllers/API/department";
import { fireEvent, render, screen, waitFor } from "@/test/test-utils";
import type { DepartmentTreeNode } from "@/types/api/department";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/controllers/API/department", () => ({
  getDepartmentTreeApi: vi.fn(),
}));

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => promise),
}));

vi.mock("@/components/bs-ui/tabs", () => ({
  Tabs: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TabsContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TabsList: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TabsTrigger: ({ children }: { children: React.ReactNode }) => (
    <button type="button">{children}</button>
  ),
}));

vi.mock("@/pages/DepartmentPage/components/DepartmentTree", () => ({
  DepartmentTree: () => <div data-testid="department-tree" />,
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
  path: "1/",
  sort_order: 0,
  source: "local",
  status: "active",
  member_count: 1,
  children: [],
};

const mockedGetDepartmentTreeApi = vi.mocked(getDepartmentTreeApi);

describe("DepartmentPage member refresh", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetDepartmentTreeApi.mockResolvedValue([dept]);
  });

  it("refreshes the member table after department settings change", async () => {
    render(<DepartmentPage />);

    await screen.findByText("Root");
    expect(screen.getByTestId("members-refresh-signal")).toHaveTextContent("0");

    fireEvent.click(screen.getByRole("button", { name: "save department settings" }));

    await waitFor(() => {
      expect(screen.getByTestId("members-refresh-signal")).toHaveTextContent("1");
    });
    expect(mockedGetDepartmentTreeApi).toHaveBeenCalledTimes(2);
  });
});
