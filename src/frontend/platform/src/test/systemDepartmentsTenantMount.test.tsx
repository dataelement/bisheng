import { useEffect, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Departments from "@/pages/SystemPage/components/Departments";
import {
  getDepartmentChildrenApi,
  getDepartmentPathTreeApi,
} from "@/controllers/API/department";
import { showApiError } from "@/controllers/request";
import type { DepartmentTreeNode } from "@/types/api/department";
import type { LazyDepartmentTree } from "@/components/bs-comp/department/useLazyDepartmentTree";

vi.mock("@/contexts/locationContext", async () => {
  const { createContext } = await import("react");
  return { locationContext: createContext({ appConfig: { multiTenantEnabled: true } }) };
});
vi.mock("@/contexts/userContext", async () => {
  const { createContext } = await import("react");
  return { userContext: createContext({ user: { role: "admin", is_global_super: true } }) };
});
vi.mock("@/controllers/API/department", () => ({
  getDepartmentChildrenApi: vi.fn(),
  getDepartmentPathTreeApi: vi.fn(),
  searchDepartmentsApi: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({ showApiError: vi.fn() }));
vi.mock("@/pages/DepartmentPage/components/CreateDepartmentDialog", () => ({
  CreateDepartmentDialog: () => null,
}));
vi.mock("@/pages/DepartmentPage/components/OrganizationSearchPanel", () => ({
  OrganizationSearchPanel: ({ children }: { children: ReactNode }) => children,
}));

// Keep the real lazy-tree controller so cached and expanded branches participate
// in the success callback. Only replace its visual presentation.
vi.mock("@/components/bs-comp/department", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/bs-comp/department")>();
  return {
    ...actual,
    LazyDepartmentTree: ({ controller, onSelect }: {
      controller: LazyDepartmentTree;
      onSelect: (node: DepartmentTreeNode) => void;
    }) => (
      <div>
        {[1, 95, 96].map((id) => {
          const node = controller.getNode(id);
          return node && (
            <div key={id}>
              <button onClick={() => onSelect(node)}>select {id}</button>
              <button onClick={() => controller.toggle(node)}>expand {id}</button>
            </div>
          );
        })}
      </div>
    ),
  };
});

const state = vi.hoisted(() => ({
  mounted: false,
  rootUnavailable: false,
  empty: false,
  memberReads: vi.fn(),
}));
vi.mock("@/pages/DepartmentPage/components/MemberTable", () => ({
  MemberTable: ({ deptId, membersRefreshSignal, toolbarActions }: {
    deptId: string;
    membersRefreshSignal: number;
    toolbarActions: ReactNode;
  }) => {
    useEffect(() => {
      state.memberReads(deptId, state.mounted);
    }, [deptId, membersRefreshSignal]);
    return <div data-testid="members">{deptId}{toolbarActions}</div>;
  },
}));
vi.mock("@/pages/DepartmentPage/components/DepartmentSettingsDialog", () => ({
  DepartmentSettingsDialog: ({ dept, onMarkAsTenant }: {
    dept: DepartmentTreeNode;
    onMarkAsTenant: (id: number, name: string) => void;
  }) => <button onClick={() => onMarkAsTenant(dept.id, dept.name)}>mark tenant</button>,
}));
vi.mock("@/pages/DepartmentPage/components/MountTenantDialog", () => ({
  MountTenantDialog: ({ onMounted, onClose }: { onMounted: () => void; onClose: () => void }) => (
    <div>
      <button onClick={() => { state.mounted = true; onMounted(); }}>mount success</button>
      <button onClick={onClose}>cancel mount</button>
    </div>
  ),
}));

function department(id: number, parentId: number | null, hasChildren: boolean): DepartmentTreeNode {
  return {
    id, dept_id: `BS@${id}`, name: `Department ${id}`, parent_id: parentId,
    path: id === 1 ? "/1/" : id === 95 ? "/1/95/" : "/1/95/96/",
    sort_order: 0, source: "local", status: "active", is_tenant_root: false,
    mounted_tenant_id: null, has_children: hasChildren, children: [],
  };
}
const root = department(1, null, true);
const child = department(95, 1, true);
const descendant = department(96, 95, true);

async function openMountDialog() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // A previously opened archived view must not retain the now out-of-scope branch.
  queryClient.setQueryData(["dept:true", "children", 95], [descendant]);
  render(<QueryClientProvider client={queryClient}><Departments /></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "expand 95" }));
  fireEvent.click(await screen.findByRole("button", { name: "expand 96" }));
  await waitFor(() => expect(getDepartmentChildrenApi).toHaveBeenCalledWith(96, false));
  fireEvent.click(screen.getByRole("button", { name: "select 95" }));
  await waitFor(() => expect(screen.getByTestId("members")).toHaveTextContent("BS@95"));
  fireEvent.click(screen.getByRole("button", { name: "bs:department.settings" }));
  fireEvent.click(screen.getByRole("button", { name: "mark tenant" }));
  return queryClient;
}

describe("System department tenant mount refresh", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.mounted = false;
    state.rootUnavailable = false;
    state.empty = false;
    vi.mocked(getDepartmentChildrenApi).mockImplementation(async (parentId) => {
      if (state.mounted && (parentId === 95 || parentId === 96)) {
        throw new Error("21009: outside Root directory");
      }
      if (state.mounted && state.rootUnavailable) throw new Error("directory unavailable");
      if (state.mounted && state.empty) return [];
      if (parentId == null) return [root];
      if (parentId === 1) return state.mounted ? [] : [child];
      if (parentId === 95) return [descendant];
      return [];
    });
    vi.mocked(getDepartmentPathTreeApi).mockRejectedValue(new Error("21009: stale selection"));
  });

  it("reloads the Root view without reading the mounted department or its descendants", async () => {
    const queryClient = await openMountDialog();
    vi.mocked(getDepartmentChildrenApi).mockClear();
    fireEvent.click(screen.getByRole("button", { name: "mount success" }));

    await waitFor(() => expect(screen.getByTestId("members")).toHaveTextContent("BS@1"));
    await waitFor(() => expect(getDepartmentChildrenApi).toHaveBeenCalledWith(1, false));
    expect(getDepartmentChildrenApi).toHaveBeenCalledWith(null, false);
    expect(getDepartmentChildrenApi).not.toHaveBeenCalledWith(95, false);
    expect(getDepartmentChildrenApi).not.toHaveBeenCalledWith(96, false);
    expect(getDepartmentPathTreeApi).not.toHaveBeenCalled();
    expect(state.memberReads).not.toHaveBeenCalledWith("BS@95", true);
    expect(screen.queryByRole("button", { name: "select 95" })).not.toBeInTheDocument();
    expect(queryClient.getQueryData(["dept:true", "children", 95])).toBeUndefined();
    expect(showApiError).not.toHaveBeenCalled();
  });

  it("keeps the current department when mounting is cancelled", async () => {
    await openMountDialog();
    vi.mocked(getDepartmentChildrenApi).mockClear();
    fireEvent.click(screen.getByRole("button", { name: "cancel mount" }));
    expect(screen.getByTestId("members")).toHaveTextContent("BS@95");
    expect(getDepartmentChildrenApi).not.toHaveBeenCalled();
    expect(showApiError).not.toHaveBeenCalled();
  });

  it("clears the stale selection when the refreshed directory is empty", async () => {
    await openMountDialog();
    state.empty = true;
    fireEvent.click(screen.getByRole("button", { name: "mount success" }));
    await screen.findByText("bs:department.selectDept");
    expect(screen.queryByTestId("members")).not.toBeInTheDocument();
    expect(getDepartmentPathTreeApi).not.toHaveBeenCalled();
    expect(showApiError).not.toHaveBeenCalled();
  });

  it("surfaces a real directory refresh failure without restoring stale department data", async () => {
    await openMountDialog();
    state.rootUnavailable = true;
    fireEvent.click(screen.getByRole("button", { name: "mount success" }));
    await waitFor(() => expect(showApiError).toHaveBeenCalledWith(new Error("directory unavailable")));
    expect(screen.queryByTestId("members")).not.toBeInTheDocument();
    expect(getDepartmentPathTreeApi).not.toHaveBeenCalled();
  });
});
