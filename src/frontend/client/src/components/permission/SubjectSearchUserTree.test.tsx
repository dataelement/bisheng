import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useCallback, useState } from "react";

import type { PermissionUserRow, SelectedSubject } from "~/api/permission";
import { SubjectSearchUserTree } from "./SubjectSearchUserTree";

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

const departments = [
  {
    id: 1,
    dept_id: "dept-1",
    name: "集团",
    parent_id: null,
    children: [
      { id: 2, dept_id: "dept-2", name: "研发部", parent_id: 1, children: [] },
      { id: 3, dept_id: "dept-3", name: "项目组", parent_id: 1, children: [] },
    ],
  },
];

const multiDepartmentUser: PermissionUserRow = {
  user_id: 7,
  user_name: "Alice",
  external_id: "EMP007",
  primary_department_path: "集团/研发部",
  department_paths: ["集团/研发部", "集团/项目组"],
  department_memberships: [
    {
      department_id: 2,
      dept_id: "dept-2",
      name: "研发部",
      path: "集团/研发部",
      is_primary: true,
    },
    {
      department_id: 3,
      dept_id: "dept-3",
      name: "项目组",
      path: "集团/项目组",
      is_primary: false,
    },
  ],
};

function ControlledTree({
  grantUsersApi,
  disabledIds = [],
}: {
  grantUsersApi: jest.Mock;
  disabledIds?: number[];
}) {
  const [value, setValue] = useState<SelectedSubject[]>([]);
  const loadDepartments = useCallback(async () => departments, []);
  return (
    <SubjectSearchUserTree
      value={value}
      onChange={setValue}
      resourceType="knowledge_space"
      resourceId="space-1"
      disabledIds={disabledIds}
      loadDepartments={loadDepartments}
      grantUsersApi={grantUsersApi}
    />
  );
}

describe("SubjectSearchUserTree", () => {
  afterEach(() => {
    jest.useRealTimers();
  });

  it("shows department display names in the knowledge-resource user tree", async () => {
    const loadDepartments = jest.fn().mockResolvedValue([
      {
        id: 10,
        dept_id: "dept-10",
        name: "北京首钢股份有限公司",
        short_name: "首钢股份",
        display_name: "首钢股份",
        parent_id: null,
        children: [],
      },
      {
        id: 11,
        dept_id: "dept-11",
        name: "无简称部门",
        short_name: null,
        display_name: "无简称部门",
        parent_id: null,
        children: [],
      },
    ]);

    render(
      <SubjectSearchUserTree
        value={[]}
        onChange={jest.fn()}
        resourceType="knowledge_space"
        resourceId="space-1"
        loadDepartments={loadDepartments}
        grantUsersApi={jest.fn().mockResolvedValue([])}
      />,
    );

    expect(await screen.findByText("首钢股份")).toHaveAttribute("title", "首钢股份");
    expect(screen.getByText("无简称部门")).toHaveAttribute("title", "无简称部门");
    expect(screen.queryByText("北京首钢股份有限公司")).not.toBeInTheDocument();
  });

  it("loads direct members only after expanding a department and supports paging", async () => {
    const grantUsersApi = jest.fn().mockImplementation(
      async (_resourceType, _resourceId, params) => {
        if (params.department_id === 2 && params.page === 1) return [multiDepartmentUser];
        return [];
      },
    );

    render(<ControlledTree grantUsersApi={grantUsersApi} />);

    const rootDepartment = await screen.findByTestId("permission-user-tree-department-1");
    expect(grantUsersApi).not.toHaveBeenCalled();
    fireEvent.click(rootDepartment);
    const department = await screen.findByTestId("permission-user-tree-department-2");
    expect(within(department).queryByRole("checkbox")).not.toBeInTheDocument();

    fireEvent.click(department);
    expect(await screen.findByTestId("permission-user-tree-row-2-7")).toBeInTheDocument();
    expect(grantUsersApi).toHaveBeenCalledWith(
      "knowledge_space",
      "space-1",
      { keyword: "", page: 1, page_size: 50, department_id: 2 },
      { signal: expect.any(AbortSignal) },
    );

    fireEvent.click(screen.getByRole("button", { name: "com_permission.load_more" }));
    await waitFor(() => expect(grantUsersApi).toHaveBeenLastCalledWith(
      "knowledge_space",
      "space-1",
      { keyword: "", page: 2, page_size: 50, department_id: 2 },
      { signal: expect.any(AbortSignal) },
    ));
  });

  it("groups search results under every visible membership and synchronizes selection by user id", async () => {
    jest.useFakeTimers();
    const grantUsersApi = jest.fn().mockResolvedValue([multiDepartmentUser]);

    render(<ControlledTree grantUsersApi={grantUsersApi} />);
    await screen.findByText("集团");

    fireEvent.change(screen.getByPlaceholderText("com_permission.search_user_by_name_or_account"), {
      target: { value: "Ali" },
    });
    await act(async () => {
      jest.advanceTimersByTime(300);
    });

    const rows = await screen.findAllByText("Alice");
    expect(rows).toHaveLength(2);
    fireEvent.click(screen.getByTestId("permission-user-tree-row-2-7"));
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    screen.getAllByRole("checkbox").forEach((checkbox) => {
      expect(checkbox).toHaveAttribute("data-state", "checked");
    });

    fireEvent.click(screen.getByTestId("permission-user-tree-row-3-7"));
    screen.getAllByRole("checkbox").forEach((checkbox) => {
      expect(checkbox).toHaveAttribute("data-state", "unchecked");
    });
  });

  it("keeps every occurrence disabled for an already granted user", async () => {
    jest.useFakeTimers();
    const grantUsersApi = jest.fn().mockResolvedValue([multiDepartmentUser]);

    render(<ControlledTree grantUsersApi={grantUsersApi} disabledIds={[7]} />);
    await screen.findByText("集团");
    fireEvent.change(screen.getByPlaceholderText("com_permission.search_user_by_name_or_account"), {
      target: { value: "Ali" },
    });
    await act(async () => {
      jest.advanceTimersByTime(300);
    });

    await screen.findAllByText("Alice");
    screen.getAllByRole("checkbox").forEach((checkbox) => {
      expect(checkbox).toBeDisabled();
    });
    expect(screen.getAllByText("com_permission.already_granted")).toHaveLength(2);
  });

  it("loads unassigned users independently and retries a failed request", async () => {
    const unassignedUser: PermissionUserRow = {
      user_id: 9,
      user_name: "No Department",
      department_memberships: [],
    };
    const grantUsersApi = jest.fn()
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce([unassignedUser]);

    render(<ControlledTree grantUsersApi={grantUsersApi} />);

    fireEvent.click(await screen.findByTestId("permission-user-tree-unassigned"));
    fireEvent.click(await screen.findByRole("button", { name: "com_permission.retry" }));

    expect(await screen.findByText("No Department")).toBeInTheDocument();
    expect(grantUsersApi).toHaveBeenLastCalledWith(
      "knowledge_space",
      "space-1",
      { keyword: "", page: 1, page_size: 50, unassigned: true },
      { signal: expect.any(AbortSignal) },
    );
  });

  it("restores cached browsing rows after clearing a search", async () => {
    jest.useFakeTimers();
    const departmentUser = { ...multiDepartmentUser, department_memberships: [multiDepartmentUser.department_memberships![0]] };
    const grantUsersApi = jest.fn().mockImplementation(
      async (_resourceType, _resourceId, params) => {
        if (params.department_id === 2) return [departmentUser];
        return [];
      },
    );

    render(<ControlledTree grantUsersApi={grantUsersApi} />);
    fireEvent.click(await screen.findByTestId("permission-user-tree-department-1"));
    fireEvent.click(await screen.findByTestId("permission-user-tree-department-2"));
    await screen.findByTestId("permission-user-tree-row-2-7");

    const input = screen.getByPlaceholderText("com_permission.search_user_by_name_or_account");
    fireEvent.change(input, { target: { value: "missing" } });
    await act(async () => {
      jest.advanceTimersByTime(300);
    });
    await screen.findByText("com_permission.empty_search");

    fireEvent.change(input, { target: { value: "" } });
    expect(await screen.findByTestId("permission-user-tree-row-2-7")).toBeInTheDocument();
    expect(grantUsersApi).toHaveBeenCalledTimes(3);
  });
});
