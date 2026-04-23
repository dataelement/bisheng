import { render, screen, waitFor } from "@/test/test-utils";
import { DepartmentKnowledgeSpaceApprovalDialog } from "@/pages/BuildPage/bench/DepartmentKnowledgeSpaceApprovalDialog";
import { DepartmentKnowledgeSpaceManagerDialog } from "@/pages/BuildPage/bench/DepartmentKnowledgeSpaceManagerDialog";
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
    SearchInput: React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>((props, ref) => (
      <input ref={ref} {...props} />
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

import { getDepartmentTreeApi } from "@/controllers/API/department";
import {
  getDepartmentKnowledgeSpaceApprovalSettingsApi,
  getDepartmentKnowledgeSpacesApi,
} from "@/controllers/API/departmentKnowledgeSpace";

const mockedGetDepartmentTreeApi = vi.mocked(getDepartmentTreeApi);
const mockedGetDepartmentKnowledgeSpacesApi = vi.mocked(getDepartmentKnowledgeSpacesApi);
const mockedGetDepartmentKnowledgeSpaceApprovalSettingsApi = vi.mocked(getDepartmentKnowledgeSpaceApprovalSettingsApi);

describe("department knowledge space dialogs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

  it("keeps the content safety switch visible in approval settings", async () => {
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
      />,
    );

    await waitFor(() => {
      expect(mockedGetDepartmentKnowledgeSpaceApprovalSettingsApi).toHaveBeenCalledWith(10);
    });

    expect(screen.getByText("开启部门知识空间上传审批")).toBeInTheDocument();
    expect(screen.getByText("开启内容安全检测")).toBeInTheDocument();
    expect(screen.getByText("开启后，上传文件会先做内容安全检测，通过后才会进入人工审批。")).toBeInTheDocument();
    expect(screen.getAllByRole("switch")).toHaveLength(2);
  });
});
