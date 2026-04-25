import { render, screen, waitFor } from "@/test/test-utils";
import { DepartmentKnowledgeSpaceApprovalDialog } from "@/pages/BuildPage/bench/DepartmentKnowledgeSpaceApprovalDialog";
import { DepartmentKnowledgeSpaceManagerDialog } from "@/pages/BuildPage/bench/DepartmentKnowledgeSpaceManagerDialog";
import KnowledgeSpace from "@/pages/BuildPage/bench/KnowledgeSpace";
import { userContext } from "@/contexts/userContext";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
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
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => Promise.resolve(promise)),
}));

vi.mock("@/controllers/API/department", () => ({
  getDepartmentTreeApi: vi.fn(),
}));

vi.mock("@/controllers/API/departmentKnowledgeSpace", () => ({
  batchCreateDepartmentKnowledgeSpacesApi: vi.fn(),
  getDepartmentKnowledgeSpacesApi: vi.fn(),
  getDepartmentKnowledgeSpaceApprovalSettingsApi: vi.fn(),
  updateDepartmentKnowledgeSpaceApprovalSettingsApi: vi.fn(),
}));

vi.mock("@/controllers/API", () => ({
  getKnowledgeConfigApi: vi.fn(),
  setKnowledgeConfigApi: vi.fn(),
}));

import { getKnowledgeConfigApi } from "@/controllers/API";
import { getDepartmentTreeApi } from "@/controllers/API/department";
import {
  getDepartmentKnowledgeSpaceApprovalSettingsApi,
  getDepartmentKnowledgeSpacesApi,
} from "@/controllers/API/departmentKnowledgeSpace";

const mockedGetKnowledgeConfigApi = vi.mocked(getKnowledgeConfigApi);
const mockedGetDepartmentTreeApi = vi.mocked(getDepartmentTreeApi);
const mockedGetDepartmentKnowledgeSpacesApi = vi.mocked(getDepartmentKnowledgeSpacesApi);
const mockedGetDepartmentKnowledgeSpaceApprovalSettingsApi = vi.mocked(getDepartmentKnowledgeSpaceApprovalSettingsApi);

describe("department knowledge space dialogs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetKnowledgeConfigApi.mockResolvedValue(null);
    mockedGetDepartmentKnowledgeSpacesApi.mockResolvedValue([]);
  });

  it("renders child departments with a deeper tree level", async () => {
    mockedGetDepartmentTreeApi.mockResolvedValue([
      {
        id: 1,
        dept_id: "root",
        name: "一级部门",
        parent_id: null,
        path: "/1",
        sort_order: 1,
        source: "manual",
        status: "active",
        member_count: 0,
        children: [
          {
            id: 2,
            dept_id: "child",
            name: "二级部门",
            parent_id: 1,
            path: "/1/2",
            sort_order: 1,
            source: "manual",
            status: "active",
            member_count: 0,
            children: [],
          },
        ],
      },
    ]);

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

  it("hides the content safety switch when the frontend flag is off", async () => {
    mockedGetDepartmentKnowledgeSpaceApprovalSettingsApi.mockResolvedValue({
      approval_enabled: true,
      sensitive_check_enabled: false,
    });

    render(
      <DepartmentKnowledgeSpaceApprovalDialog
        open
        onOpenChange={() => {}}
        space={{
          id: 10,
          name: "研发知识空间",
          department_id: 1,
          department_name: "研发部",
        }}
        showSensitiveCheckControl={false}
      />,
    );

    await waitFor(() => {
      expect(mockedGetDepartmentKnowledgeSpaceApprovalSettingsApi).toHaveBeenCalledWith(10);
    });

    expect(screen.getByText("开启部门知识空间上传审批")).toBeInTheDocument();
    expect(screen.queryByText("开启内容安全检测")).not.toBeInTheDocument();
    expect(screen.queryByText("开启后，上传文件会先做内容安全检测，通过后才会进入人工审批。")).not.toBeInTheDocument();
    expect(screen.getAllByRole("switch")).toHaveLength(1);
  });

  it("hides the content safety status tag in the department knowledge space list", async () => {
    mockedGetDepartmentKnowledgeSpacesApi.mockResolvedValue([
      {
        id: 10,
        name: "研发知识空间",
        department_id: 1,
        department_name: "研发部",
        approval_enabled: false,
        sensitive_check_enabled: false,
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

    expect(screen.getByText("审批关闭")).toBeInTheDocument();
    expect(screen.queryByText("内容安全关闭")).not.toBeInTheDocument();
  });
});
