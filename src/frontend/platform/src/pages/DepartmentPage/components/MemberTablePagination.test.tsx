import { act, cleanup, render, waitFor } from "@testing-library/react";
import { createContext } from "react";
import { afterEach, expect, it, vi } from "vitest";
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
  OrganizationMemberEditDialog: () => null,
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
