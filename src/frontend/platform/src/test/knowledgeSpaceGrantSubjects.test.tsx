import { SubjectSearchDepartment } from "@/components/bs-comp/permission/SubjectSearchDepartment";
import { SubjectSearchUserGroup } from "@/components/bs-comp/permission/SubjectSearchUserGroup";
import {
  getKnowledgeSpaceGrantDepartmentsApi,
  getKnowledgeSpaceGrantUserGroupsApi,
} from "@/controllers/API/permission";
import { render, screen, waitFor } from "@/test/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("@/controllers/API/permission", () => ({
  getKnowledgeSpaceGrantDepartmentsApi: vi.fn(),
  getKnowledgeSpaceGrantUserGroupsApi: vi.fn(),
}));

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => promise),
}));

vi.mock("@/components/bs-ui/input", () => ({
  SearchInput: ({ value, onChange, placeholder }: any) => (
    <input value={value} onChange={onChange} placeholder={placeholder} />
  ),
}));

vi.mock("@/components/bs-ui/checkBox", () => ({
  Checkbox: ({ checked, onCheckedChange }: any) => (
    <input
      type="checkbox"
      readOnly
      checked={checked}
      onClick={() => onCheckedChange?.(!checked)}
    />
  ),
}));

const mockedGetKnowledgeSpaceGrantDepartmentsApi = vi.mocked(getKnowledgeSpaceGrantDepartmentsApi);
const mockedGetKnowledgeSpaceGrantUserGroupsApi = vi.mocked(getKnowledgeSpaceGrantUserGroupsApi);

describe("Knowledge-space grant subject sources", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads the full department tree for knowledge-space permission grants", async () => {
    mockedGetKnowledgeSpaceGrantDepartmentsApi.mockResolvedValue([
      {
        id: 10,
        dept_id: "BS@10",
        name: "研发部",
        parent_id: null,
        path: "/10/",
        sort_order: 0,
        source: "local",
        status: "active",
        member_count: 0,
        children: [],
      },
    ] as any);

    render(
      <SubjectSearchDepartment
        value={[]}
        onChange={vi.fn()}
        resourceType="knowledge_space"
        resourceId="88"
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("研发部")).toBeInTheDocument();
    });

    expect(mockedGetKnowledgeSpaceGrantDepartmentsApi).toHaveBeenCalledWith("88");
  });

  it("loads the full user-group list for knowledge-space permission grants", async () => {
    mockedGetKnowledgeSpaceGrantUserGroupsApi.mockResolvedValue([
      { id: 3, group_name: "产品组" },
    ] as any);

    render(
      <SubjectSearchUserGroup
        value={[]}
        onChange={vi.fn()}
        resourceType="knowledge_space"
        resourceId="88"
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("产品组")).toBeInTheDocument();
    });

    expect(mockedGetKnowledgeSpaceGrantUserGroupsApi).toHaveBeenCalledWith("88");
  });
});
