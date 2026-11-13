import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createContext, useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import type { DepartmentMember, DepartmentTreeNode } from "@/types/api/department";
import { MemberTable } from "./MemberTable";

const mocks = vi.hoisted(() => ({ members: vi.fn() }));
vi.mock("@/controllers/API/department", () => ({
  getDepartmentMembersApi: mocks.members,
  getDepartmentAdminsApi: vi.fn(async () => []),
  getDepartmentPathTreeApi: vi.fn(async () => ({ roots: [] })),
}));
vi.mock("@/controllers/API/user", () => ({ disableUserApi: vi.fn() }));
vi.mock("@/controllers/request", () => ({ showApiError: vi.fn() }));
vi.mock("@/contexts/userContext", () => ({
  userContext: createContext({ user: { role: "admin", user_id: 1 } }),
}));
vi.mock("@/pages/LoginPage/UserPwdModal", async () => ({
  default: (await import("react")).forwardRef(() => null),
}));
vi.mock("./CreateLocalMemberDialog", () => ({
  CreateLocalMemberDialog: () => null,
}));
vi.mock("./OrganizationMemberEditDialog", () => ({
  OrganizationMemberEditDialog: ({ open, deptId }: { open: boolean; deptId: string }) =>
    open ? <div role="dialog">{deptId}</div> : null,
}));

afterEach(cleanup);

it("keeps the located page while replacing a small department with a larger department", async () => {
  const department = {
    id: 1,
    dept_id: "small",
    name: "Small",
    parent_id: null,
    path: "/1/",
    sort_order: 0,
    source: "local",
    status: "active",
    is_tenant_root: false,
    mounted_tenant_id: null,
    children: [],
  };
  const member = {
    user_id: 25,
    user_name: "Located member",
    enabled: true,
    is_primary: 0,
    source: "local",
    roles: [],
    user_groups: [],
    create_time: "2026-11-10",
  };
  let finish: (value: {
    data: (typeof member)[];
    total: number;
  }) => void = () => {};
  mocks.members.mockImplementation((deptId: string) =>
    deptId === "small"
      ? Promise.resolve({ data: [member], total: 5 })
      : new Promise((resolve) => {
          finish = resolve;
        })
  );
  const shared = {
    deptName: "Department",
    onChanged: vi.fn(),
    isPrimaryFilter: "all",
    onFilterChange: vi.fn(),
  };
  const { container, rerender } = render(
    <MemberTable {...shared} deptId="small" dept={department} />
  );
  await waitFor(() =>
    expect(container.querySelector('[data-member-row="25"]')).not.toBeNull()
  );
  rerender(
    <MemberTable
      {...shared}
      deptId="large"
      dept={{ ...department, id: 2, dept_id: "large" }}
      location={{ userId: 25, deptId: "large", page: 2, requestId: 1 }}
    />
  );
  await waitFor(() =>
    expect(mocks.members).toHaveBeenCalledWith(
      "large",
      expect.objectContaining({ page: 2 })
    )
  );
  await act(async () => {
    await Promise.resolve();
  });
  expect(
    mocks.members.mock.calls
      .filter(([deptId]) => deptId === "large")
      .map(([, parameters]) => parameters.page)
  ).toEqual([2]);
  await act(async () => finish({ data: [member], total: 35 }));
  await waitFor(() =>
    expect(container.querySelector('[data-member-row="25"]')).toHaveClass(
      "bg-primary/10"
    )
  );
  expect(
    mocks.members.mock.calls
      .filter(([deptId]) => deptId === "large")
      .map(([, parameters]) => parameters.page)
  ).toEqual([2]);
});

it("toggles descendant memberships at the heading and edits the selected department relationship", async () => {
  const department: DepartmentTreeNode = {
    id: 1,
    dept_id: "parent",
    name: "Parent department",
    parent_id: null,
    path: "/1/",
    sort_order: 0,
    source: "local",
    status: "active",
    is_tenant_root: false,
    mounted_tenant_id: null,
    children: [],
  };
  const member: DepartmentMember = {
    user_id: 25,
    user_name: "Ada",
    department_id: department.id,
    enabled: true,
    is_primary: 0,
    source: "local",
    roles: [],
    user_groups: [],
    create_time: "2026-11-12",
  };
  mocks.members.mockImplementation(async (_deptId, params) =>
    params.include_descendants
      ? {
          total: 2,
          direct_total: 1,
          data: [
            { ...member, department },
            {
              ...member,
              is_primary: 1,
              department_id: 2,
              department: { dept_id: "child", name: "Child department", status: "active" },
            },
          ],
        }
      : { data: [member], total: 1 }
  );

  function TableWithScope() {
    const [directOnly, setDirectOnly] = useState(true);
    return (
      <MemberTable
        deptId={department.dept_id}
        deptName={department.name}
        dept={department}
        onChanged={vi.fn()}
        isPrimaryFilter="all"
        onFilterChange={vi.fn()}
        directOnly={directOnly}
        onDirectOnlyChange={setDirectOnly}
      />
    );
  }

  render(<TableWithScope />);
  const user = userEvent.setup();
  const heading = screen.getByRole("heading", { name: department.name });
  const checkbox = within(heading.parentElement!).getByRole("checkbox", {
    name: "bs:organization.directMemberCount",
  });
  expect(checkbox).toBeChecked();
  expect(await screen.findByText("Ada")).toBeVisible();

  await user.click(checkbox);
  expect(checkbox).not.toBeChecked();
  const childRow = await screen.findByRole("row", { name: /Child department/ });
  expect(screen.getAllByText("Ada")).toHaveLength(2);
  expect(mocks.members).toHaveBeenLastCalledWith(
    "parent", expect.objectContaining({ page: 1, include_descendants: true })
  );
  await user.click(within(childRow).getByRole("button", { name: "edit" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("child");

  await user.click(checkbox);
  expect(checkbox).toBeChecked();
  await waitFor(() => expect(screen.queryByText("Child department")).not.toBeInTheDocument());
  expect(await screen.findByText("Ada")).toBeVisible();
});
