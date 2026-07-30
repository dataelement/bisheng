import { SubjectSearchDepartment } from "@/components/bs-comp/permission/SubjectSearchDepartment";
import { SubjectSearchUserGroup } from "@/components/bs-comp/permission/SubjectSearchUserGroup";
import {
  getDepartmentChildrenApi,
  getDepartmentPathTreeApi,
  searchDepartmentsApi,
} from "@/controllers/API/department";
import {
  getUserGroupsApi,
} from "@/controllers/API/user";
import { render, screen, waitFor, within } from "@/test/test-utils";
import { fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  // The dept picker uses the "permission" namespace; the lazy tree uses the
  // default one. Returning the key verbatim keeps both predictable.
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/controllers/API/department", () => ({
  getDepartmentChildrenApi: vi.fn(),
  searchDepartmentsApi: vi.fn(),
  getDepartmentPathTreeApi: vi.fn(),
}));

vi.mock("@/controllers/API/user", () => ({
  getUserGroupsApi: vi.fn(),
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
  // Stop propagation like the real Radix checkbox so a row click does not also
  // toggle the row's onSelect (which would cancel out the change).
  Checkbox: ({ checked, disabled, onCheckedChange }: any) => (
    <input
      type="checkbox"
      readOnly
      checked={!!checked}
      disabled={!!disabled}
      onClick={(e) => {
        e.stopPropagation();
        if (!disabled) onCheckedChange?.(!checked);
      }}
    />
  ),
}));

const mockedDeptChildren = vi.mocked(getDepartmentChildrenApi);
const mockedDeptSearch = vi.mocked(searchDepartmentsApi);
const mockedDeptPathTree = vi.mocked(getDepartmentPathTreeApi);
const mockedUserGroups = vi.mocked(getUserGroupsApi);

const node = (
  id: number,
  name: string,
  parent_id: number | null,
  path: string,
  has_children: boolean,
  matched = false,
) => ({
  id,
  dept_id: `BS@${id}`,
  name,
  parent_id,
  path,
  sort_order: 0,
  source: "local",
  status: "active",
  is_tenant_root: false,
  mounted_tenant_id: null,
  has_children,
  matched,
  children: [] as any[],
});

const rowOf = (text: string) =>
  (screen.getByText(text).closest("[data-depth]") as HTMLElement);

describe("permission subject discovery business boundary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedDeptChildren.mockResolvedValue([] as any);
    mockedDeptSearch.mockResolvedValue({ roots: [], total_matches: 0, truncated: false } as any);
    mockedDeptPathTree.mockResolvedValue({ roots: [], total_matches: 0, truncated: false } as any);
    mockedUserGroups.mockResolvedValue([] as any);
  });

  it("loads grant departments from the organization API without member counts", async () => {
    mockedDeptChildren.mockResolvedValue([node(10, "研发部", null, "/10/", false)] as any);

    render(
      <SubjectSearchDepartment
        value={[]}
        onChange={vi.fn()}
        resourceType="knowledge_space"
        resourceId="88"
      />,
    );

    await screen.findByText("研发部");
    expect(mockedDeptChildren).toHaveBeenCalledWith(null, false);
    // member_count was removed (F038 / reversed F027) — no "(N)" suffix renders.
    expect(screen.queryByText(/\(\d+\)/)).not.toBeInTheDocument();
  });

  it("uses the same organization API for workflow grants", async () => {
    mockedDeptChildren.mockResolvedValue([node(10, "研发部", null, "/10/", false)] as any);

    render(
      <SubjectSearchDepartment
        value={[]}
        onChange={vi.fn()}
        resourceType="workflow"
        resourceId="wf-1"
      />,
    );

    await screen.findByText("研发部");
    expect(mockedDeptChildren).toHaveBeenCalledWith(null, false);
  });

  it("browses the plain org tree when allowOrganizationTree and no resource is given", async () => {
    mockedDeptChildren.mockResolvedValue([node(10, "研发部", null, "/10/", false)] as any);

    render(<SubjectSearchDepartment value={[]} onChange={vi.fn()} allowOrganizationTree />);

    await screen.findByText("研发部");
    expect(mockedDeptChildren).toHaveBeenCalledWith(null, false);
  });

  it("marks descendants checked + disabled (implicit) when an ancestor is selected with include-children — decision 9 (path-based)", async () => {
    mockedDeptChildren.mockResolvedValue([node(10, "研发部", null, "/10/", true)] as any);
    // Search returns the backend's pruned tree (rendered fully expanded), so the
    // descendant 平台组 becomes visible under its selected ancestor 研发部.
    mockedDeptSearch.mockResolvedValue({
      roots: [
        { ...node(10, "研发部", null, "/10/", true), children: [node(11, "平台组", 10, "/10/11/", false, true)] },
      ],
      total_matches: 1,
      truncated: false,
    } as any);

    render(
      <SubjectSearchDepartment
        value={[{ type: "department", id: 10, name: "研发部", include_children: true } as any]}
        onChange={vi.fn()}
        resourceType="knowledge_space"
        resourceId="88"
        includeChildren
      />,
    );

    // Root load primes nodeMap[10].path so implicit selection can be computed.
    await screen.findByText("研发部");
    fireEvent.change(screen.getByPlaceholderText("search.department"), { target: { value: "平台组" } });

    await screen.findByText("平台组");
    const childCheckbox = within(rowOf("平台组")).getByRole("checkbox");
    expect(childCheckbox).toBeChecked();
    expect(childCheckbox).toBeDisabled();
  });

  it("summarizes only the explicit picks, never the materialized subtree — decision 10", async () => {
    mockedDeptChildren.mockResolvedValue([node(10, "研发部", null, "/10/", true)] as any);
    const onSelectionSummaryChange = vi.fn();

    render(
      <SubjectSearchDepartment
        value={[{ type: "department", id: 10, name: "研发部", include_children: true } as any]}
        onChange={vi.fn()}
        resourceType="knowledge_space"
        resourceId="88"
        includeChildren
        onSelectionSummaryChange={onSelectionSummaryChange}
      />,
    );

    await waitFor(() =>
      expect(onSelectionSummaryChange).toHaveBeenLastCalledWith([
        { type: "department", id: 10, name: "研发部", include_children: true },
      ]),
    );
  });

  it("shows already-granted departments as checked and disabled", async () => {
    mockedDeptChildren.mockResolvedValue([node(10, "研发部", null, "/10/", false)] as any);

    render(
      <SubjectSearchDepartment
        value={[]}
        onChange={vi.fn()}
        resourceType="knowledge_space"
        resourceId="88"
        disabledIds={[10]}
      />,
    );

    await screen.findByText("研发部");
    const checkbox = within(rowOf("研发部")).getByRole("checkbox");
    expect(checkbox).toBeChecked();
    expect(checkbox).toBeDisabled();
  });

  it("adds a department carrying the current include-children flag when toggled on", async () => {
    mockedDeptChildren.mockResolvedValue([node(10, "研发部", null, "/10/", false)] as any);
    const onChange = vi.fn();

    render(
      <SubjectSearchDepartment
        value={[]}
        onChange={onChange}
        resourceType="knowledge_space"
        resourceId="88"
        includeChildren
      />,
    );

    await screen.findByText("研发部");
    fireEvent.click(within(rowOf("研发部")).getByRole("checkbox"));

    expect(onChange).toHaveBeenCalledWith([
      { type: "department", id: 10, name: "研发部", include_children: true },
    ]);
  });

  it("loads user groups from the user-group business API", async () => {
    mockedUserGroups.mockResolvedValue([{ id: 3, group_name: "产品组" }] as any);

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

    expect(mockedUserGroups).toHaveBeenCalledWith({});
  });
});
