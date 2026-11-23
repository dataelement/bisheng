import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OrganizationSearchPanel } from "./OrganizationSearchPanel";

const mocks = vi.hoisted(() => ({ search: vi.fn(), error: vi.fn() }));
vi.mock("@/controllers/API/organization", () => ({
  searchOrganizationApi: mocks.search,
}));
vi.mock("@/controllers/request", () => ({ showApiError: mocks.error }));

const member = {
  user_id: 25,
  user_name: "Ada",
  person_id: "P25",
  enabled: true,
  is_primary: false,
  department: {
    id: 2,
    dept_id: "product",
    name: "Product",
    status: "active",
    path: "Root / Product",
  },
};
const department = {
  id: 2,
  dept_id: "product",
  name: "Product",
  status: "active",
  parent_path: "Root",
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.search.mockImplementation(async ({ kind }) => ({
    data: kind === "members" ? [member] : [department],
    total: 1,
  }));
});
afterEach(cleanup);

function panel(onSelectMember = vi.fn(async () => {})) {
  render(
    <OrganizationSearchPanel
      includeArchived={false}
      preferredDepartmentId={2}
      onSelectDepartment={vi.fn(async () => {})}
      onSelectMember={onSelectMember}
    >
      <div data-testid="tree">Original selected tree</div>
    </OrganizationSearchPanel>
  );
  return screen.getByRole("searchbox");
}

describe("organization name search", () => {
  it("loads both groups and clears only after a successful member location", async () => {
    let finish: () => void = () => {};
    const locate = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        })
    );
    const input = panel(locate);
    fireEvent.change(input, { target: { value: "Ada" } });
    await screen.findByText("Ada");
    expect(screen.getByText("Root")).toBeVisible();
    expect(
      screen.getByText(/Productbs:organization.secondarySuffix/)
    ).toBeVisible();
    expect(screen.getByTestId("tree")).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Ada/ }));
    expect(input).toHaveValue("Ada");
    expect(locate).toHaveBeenCalledWith(member);
    await act(async () => finish());
    expect(input).toHaveValue("");
    expect(screen.getByTestId("tree")).toBeVisible();
  });

  it("retains the result and keyword after a location failure", async () => {
    const failure = new Error("Membership changed");
    const input = panel(
      vi.fn(async () => {
        throw failure;
      })
    );
    fireEvent.change(input, { target: { value: "Ada" } });
    await screen.findByText("Ada");
    fireEvent.click(screen.getByRole("button", { name: /Ada/ }));
    await waitFor(() => expect(mocks.error).toHaveBeenCalledWith(failure));
    expect(input).toHaveValue("Ada");
    expect(screen.getByText("Ada")).toBeVisible();
  });

  it("suppresses both searches during IME composition and restores the original tree on clear", async () => {
    const input = panel();
    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: "Ada" } });
    await new Promise((resolve) => setTimeout(resolve, 350));
    expect(mocks.search).not.toHaveBeenCalled();
    fireEvent.compositionEnd(input, { data: "Ada" });
    await screen.findByText("Ada");
    expect(mocks.search).toHaveBeenCalledTimes(2);
    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getByTestId("tree")).toBeVisible();
    expect(screen.queryByText("Ada")).not.toBeInTheDocument();
  });

  it("ignores an older query response for both result groups", async () => {
    const pending: Array<
      (value: { data: (typeof department)[]; total: number }) => void
    > = [];
    mocks.search.mockImplementation(({ keyword, kind }) =>
      keyword === "Old"
        ? new Promise((resolve) => pending.push(resolve))
        : Promise.resolve({
            data:
              kind === "departments" ? [{ ...department, name: "New" }] : [],
            total: kind === "departments" ? 1 : 0,
          })
    );
    const input = panel();
    fireEvent.change(input, { target: { value: "Old" } });
    await waitFor(() => expect(pending).toHaveLength(2));
    fireEvent.change(input, { target: { value: "New" } });
    await screen.findByText("New");
    await act(async () => {
      pending.forEach((resolve) =>
        resolve({ data: [{ ...department, name: "Old" }], total: 1 })
      );
    });
    expect(screen.getByText("New")).toBeVisible();
    expect(screen.queryByText("Old")).not.toBeInTheDocument();
  });
});
