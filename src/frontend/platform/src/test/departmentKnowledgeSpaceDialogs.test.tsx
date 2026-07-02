import { fireEvent, render, screen, waitFor, within } from "@/test/test-utils";
import { DepartmentKnowledgeSpaceManagerDialog } from "@/pages/BuildPage/bench/DepartmentKnowledgeSpaceManagerDialog";
import KnowledgeSpace from "@/pages/BuildPage/bench/KnowledgeSpace";
import { userContext } from "@/contexts/userContext";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string | { defaultValue?: string }) => {
      if (typeof fallback === "string") return fallback;
      if (fallback && typeof fallback === "object" && "defaultValue" in fallback) return fallback.defaultValue || key;
      return key;
    },
  }),
}));

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  useToast: () => ({
    toast: vi.fn(),
  }),
}));

vi.mock("@/components/bs-ui/input", async () => {
  const React = await import("react");
  return {
    Input: React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>((props, ref) => (
      <input ref={ref} {...props} />
    )),
    NonNegativeInput: React.forwardRef<
      HTMLInputElement,
      React.ComponentProps<"input"> & { onValueChange?: (value: number) => void }
    >(({ defaultValue, onValueChange, value, ...props }, ref) => (
      <input
        ref={ref}
        {...props}
        value={value ?? defaultValue ?? ""}
        onChange={(event) => onValueChange?.(Number(event.target.value))}
      />
    )),
    SearchInput: React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>((props, ref) => (
      <input ref={ref} {...props} />
    )),
    Textarea: React.forwardRef<HTMLTextAreaElement, React.ComponentProps<"textarea">>((props, ref) => (
      <textarea ref={ref} {...props} />
    )),
  };
});

vi.mock("@/controllers/request", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => Promise.resolve(promise)),
}));

vi.mock("@/controllers/API/department", () => ({
  getDepartmentChildrenApi: vi.fn(() => Promise.resolve([])),
  searchDepartmentsApi: vi.fn(() => Promise.resolve({ roots: [], total_matches: 0, truncated: false })),
  getDepartmentPathTreeApi: vi.fn(() => Promise.resolve({ roots: [], total_matches: 0, truncated: false })),
}));

vi.mock("@/controllers/API/departmentKnowledgeSpace", () => ({
  batchCreateDepartmentKnowledgeSpacesApi: vi.fn(),
  getDepartmentKnowledgeSpacesApi: vi.fn(),
  setDepartmentKnowledgeSpacesVisibilityApi: vi.fn(),
}));

vi.mock("@/controllers/API", () => ({
  getKnowledgeConfigApi: vi.fn(),
  setKnowledgeConfigApi: vi.fn(),
}));

import { getKnowledgeConfigApi } from "@/controllers/API";
import { getDepartmentChildrenApi } from "@/controllers/API/department";
import {
  getDepartmentKnowledgeSpacesApi,
  setDepartmentKnowledgeSpacesVisibilityApi,
} from "@/controllers/API/departmentKnowledgeSpace";

const mockedGetKnowledgeConfigApi = vi.mocked(getKnowledgeConfigApi);
const mockedChildren = vi.mocked(getDepartmentChildrenApi);
const mockedGetDepartmentKnowledgeSpacesApi = vi.mocked(getDepartmentKnowledgeSpacesApi);
const mockedSetVisibility = vi.mocked(setDepartmentKnowledgeSpacesVisibilityApi);

// Build a lazy children-map mock: parent_id (null=root) -> child DepartmentTreeNodes.
const lazyNode = (id: number, name: string, parent_id: number | null, has_children: boolean) => ({
  id, dept_id: String(id), name, parent_id, path: `/${parent_id ? `${parent_id}/` : ""}${id}/`,
  sort_order: id, source: "manual", status: "active",
  is_tenant_root: false, mounted_tenant_id: null, has_children, matched: false, children: [],
});
function mockLazyChildren(map: Record<string, ReturnType<typeof lazyNode>[]>) {
  mockedChildren.mockImplementation((parentId: number | null) =>
    Promise.resolve((map[parentId == null ? "null" : String(parentId)] ?? []) as any),
  );
}

describe("department knowledge space dialogs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetKnowledgeConfigApi.mockResolvedValue(null);
    mockedGetDepartmentKnowledgeSpacesApi.mockResolvedValue([]);
  });

  it("renders child departments with a deeper tree level", async () => {
    // Lazy: root layer = 一级部门 (has children); expanding loads 二级部门.
    mockLazyChildren({
      null: [lazyNode(1, "一级部门", null, true)],
      "1": [lazyNode(2, "二级部门", 1, false)],
    });

    render(
      <DepartmentKnowledgeSpaceManagerDialog
        open
        onOpenChange={() => {}}
      />,
    );

    const childLabel = await screen.findByText("二级部门");
    const childRow = childLabel.closest("[data-depth]");

    expect(childRow).toHaveAttribute("data-depth", "1");
  });

  it("does not render approval settings controls in the department knowledge space list", async () => {
    mockedGetDepartmentKnowledgeSpacesApi.mockResolvedValue([
      {
        id: 10,
        name: "研发知识空间",
        department_id: 1,
        department_name: "研发部",
      },
    ]);

    render(
      <userContext.Provider
        value={{
          user: { user_id: 1, role: "admin" },
          setUser: vi.fn(),
          savedComponents: [],
          addSavedComponent: vi.fn(),
          checkComponentsName: vi.fn(),
          delComponent: vi.fn(),
        } as any}
      >
        <KnowledgeSpace />
      </userContext.Provider>,
    );

    await screen.findByText("研发知识空间");

    await waitFor(() => {
      expect(mockedGetDepartmentKnowledgeSpacesApi).toHaveBeenCalled();
    });

    expect(screen.queryByText("审批设置")).not.toBeInTheDocument();
    expect(screen.queryByText("审批关闭")).not.toBeInTheDocument();
    expect(screen.queryByText("内容安全关闭")).not.toBeInTheDocument();
  });

  it("renders configured/hidden badges and stages a hide on uncheck + save", async () => {
    mockLazyChildren({
      null: [lazyNode(1, "可见部门", null, false), lazyNode(2, "隐藏部门", null, false)],
    });
    mockedGetDepartmentKnowledgeSpacesApi.mockResolvedValue([
      { id: 10, name: "可见部门的知识空间", department_id: 1, department_name: "可见部门", is_hidden: false },
      { id: 11, name: "隐藏部门的知识空间", department_id: 2, department_name: "隐藏部门", is_hidden: true },
    ] as any);
    mockedSetVisibility.mockResolvedValue({ changed: 1 });

    render(<DepartmentKnowledgeSpaceManagerDialog open onOpenChange={() => {}} />);

    await screen.findByText("可见部门");
    // Visible binding shows the "已配置" badge; a hidden one shows "已隐藏".
    expect(screen.getByText("已配置")).toBeInTheDocument();
    expect(screen.getByText("已隐藏")).toBeInTheDocument();
    // No diff yet: the visible department starts checked, the hidden one unchecked.
    expect(screen.getByText("暂无变更")).toBeInTheDocument();

    // Uncheck the already-configured department -> stages a hide.
    const visibleRow = screen.getByText("可见部门").closest("[data-depth]") as HTMLElement;
    fireEvent.click(within(visibleRow).getByRole("checkbox"));
    await screen.findByText(/待隐藏/);

    fireEvent.click(screen.getByText("保存"));
    await waitFor(() => {
      expect(mockedSetVisibility).toHaveBeenCalledWith([1], true);
    });
  });
});
