import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { createContext, StrictMode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useMemberTableController } from "./MemberTable";

const mocks = vi.hoisted(() => ({ members: vi.fn() }));
vi.mock("@/controllers/API/department", () => ({
  getDepartmentMembersApi: mocks.members,
  getDepartmentAdminsApi: vi.fn(async () => []),
  getDepartmentPathTreeApi: vi.fn(async () => ({ roots: [] })),
}));
vi.mock("@/controllers/API/user", () => ({ disableUserApi: vi.fn() }));
vi.mock("@/controllers/request", () => ({ showApiError: vi.fn() }));
vi.mock("@/contexts/userContext", () => ({
  userContext: createContext({ user: {} }),
}));
vi.mock("./MemberTableView", () => ({ MemberTableView: () => null }));

const department = {
  id: 1,
  dept_id: "department",
  name: "Department",
  parent_id: null,
  path: "/1/",
  sort_order: 0,
  source: "local",
  status: "active",
  is_tenant_root: false,
  mounted_tenant_id: null,
  children: [],
};
const props = {
  deptId: "department",
  deptName: "Department",
  dept: department,
  isPrimaryFilter: "all",
  onFilterChange: vi.fn(),
  onChanged: vi.fn(),
};
beforeEach(() => {
  vi.clearAllMocks();
  mocks.members.mockResolvedValue({
    data: [{ user_id: 25, user_name: "Ada", enabled: true }],
    total: 45,
  });
});
afterEach(cleanup);

it("requests the located page and keeps the highlight in React StrictMode", async () => {
  const location = { deptId: "department", userId: 25, page: 2, requestId: 1 };
  const { result } = renderHook(
    () => useMemberTableController({ ...props, location }),
    { wrapper: StrictMode }
  );
  await waitFor(() => expect(result.current.members).toHaveLength(1));
  expect(result.current.page).toBe(2);
  expect(result.current.highlightUserId).toBe(25);
  expect(mocks.members).toHaveBeenLastCalledWith("department", {
    page: 2,
    limit: 20,
    is_primary: undefined,
  });
  await act(async () => result.current.handlePageChange(1));
  expect(result.current.highlightUserId).toBeNull();
});

it("highlights the located member for three seconds after each search", async () => {
  vi.useFakeTimers();
  try {
    const location = { deptId: "department", userId: 25, page: 2, requestId: 1 };
    const { result, rerender, unmount } = renderHook(
      ({ location }) => useMemberTableController({ ...props, location }),
      { initialProps: { location } }
    );
    await act(async () => {});
    act(() => vi.advanceTimersToNextFrame());
    act(() => vi.advanceTimersByTime(2500));
    expect(result.current.highlightUserId).toBe(25);

    rerender({ location: { ...location, requestId: 2 } });
    await act(async () => {});
    act(() => vi.advanceTimersToNextFrame());
    act(() => vi.advanceTimersByTime(2999));
    expect(result.current.highlightUserId).toBe(25);
    act(() => vi.advanceTimersByTime(1));
    expect(result.current.highlightUserId).toBeNull();
    unmount();
  } finally {
    vi.useRealTimers();
  }
});

it("does not apply a response from the previously selected department", async () => {
  let finish: (value: {
    data: { user_id: number; user_name: string }[];
    total: number;
  }) => void = () => {};
  mocks.members.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  const { result, rerender } = renderHook(
    ({ deptId }) => useMemberTableController({ ...props, deptId }),
    { initialProps: { deptId: "old" } }
  );
  rerender({ deptId: "new" });
  await waitFor(() => expect(result.current.members).toHaveLength(1));
  await act(async () =>
    finish({ data: [{ user_id: 99, user_name: "Old department" }], total: 1 })
  );
  expect(result.current.members[0].user_id).toBe(25);
});
