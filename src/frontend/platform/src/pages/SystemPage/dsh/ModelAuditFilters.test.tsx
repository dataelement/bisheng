import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { userContext } from "@/contexts/userContext";
import type { ContextType } from "react";
import type { AuditUserPage } from "@/types/dshModelAudit";
const api = vi.hoisted(() => ({
  page: vi.fn(),
  groups: vi.fn(),
  users: vi.fn(),
  models: vi.fn(),
  mode: vi.fn(),
  tenants: vi.fn(),
}));
vi.mock("@/controllers/API/dshModelAudit", () => ({
  getModelAudit: api.page,
  getAuditGroups: api.groups,
  getAuditUsers: api.users,
  getAuditModels: api.models,
  getAuditMode: api.mode,
  getAuditReadiness: async () => ({
    status_ready: true,
    name_ready: true,
    indexing_pending: false,
  }),
}));
vi.mock("@/controllers/API/tenant", () => ({ getTenantsApi: api.tenants }));
import { ModelAuditPanel, ModelAuditRequests } from "./ModelAuditPanel";
function applyFilters() {
  fireEvent.click(
    screen.getByRole("button", { name: "dsh.modelAuditView.search" }),
  );
}
function advanced() {
  fireEvent.click(
    screen.getByRole("button", { name: /^dsh.modelAuditView.advancedFilters/ }),
  );
}
function renderRequests() {
  render(<ModelAuditRequests tenantId={2} initialView="unassociated" />);
}
function model() {
  return screen.getByRole("combobox", {
    name: "dsh.modelAuditView.filters.model_name",
  });
}
beforeEach(() => {
  vi.resetAllMocks();
  api.page.mockResolvedValue({
    items: [],
    next_cursor: null,
    progress: { last_write_at: null },
  });
  api.groups.mockImplementation(async (q, s) => {
    await api.page(q, s);
    return {
      items: [],
      next_cursor: null,
      scan_limited: false,
      progress: {
        status_ready: true,
        name_ready: true,
        indexing_pending: false,
      },
    };
  });
  api.models.mockResolvedValue({
    data: [{ id: 42, name: "Provider / Available" }],
    total: 1,
  });
  api.users.mockResolvedValue({
    data: [{ user_id: 20, user_name: "Alice" }],
    total: 1,
  });
  api.mode.mockResolvedValue({ mode: "OFF", version: 0 });
  api.tenants.mockResolvedValue({
    data: [
      { id: 1, tenant_name: "First tenant", tenant_code: "first" },
      { id: 2, tenant_name: "Second tenant", tenant_code: "second" },
    ],
    total: 2,
  });
});
describe("unified audit filters", () => {
  it("hides the model and replaces four axes with one status filter", async () => {
    renderRequests();
    await screen.findByText("dsh.modelAuditView.empty");
    expect(
      screen.queryByLabelText("dsh.modelAuditView.filters.model_name"),
    ).toBeNull();
    expect(api.models).not.toHaveBeenCalled();
    advanced();
    expect(model()).toBeVisible();
    await screen.findByRole("combobox", {
      name: "dsh.modelAuditView.summary_status",
    });
    for (const key of [
      "model_result",
      "response_result",
      "usage_settlement",
      "content_status",
    ])
      expect(screen.queryByText("dsh.modelAuditView.axes." + key)).toBeNull();
  });
  it("keeps edits local and refreshes applied filters rather than the draft", async () => {
    renderRequests();
    await screen.findByText("dsh.modelAuditView.empty");
    advanced();
    fireEvent.change(model(), { target: { value: "Provider / Applied" } });
    expect(api.page).toHaveBeenCalledTimes(1);
    applyFilters();
    await waitFor(() => expect(api.page).toHaveBeenCalledTimes(2));
    fireEvent.change(model(), { target: { value: "Provider / Draft" } });
    fireEvent.click(
      screen.getByRole("button", {
        name: "dsh.modelAuditView.refresh_records",
      }),
    );
    await waitFor(() => expect(api.page).toHaveBeenCalledTimes(3));
    expect(api.page).toHaveBeenLastCalledWith(
      expect.objectContaining({ model_name: "Provider / Applied" }),
      expect.any(AbortSignal),
    );
    expect(model()).toHaveValue("Provider / Draft");
  });
  it("loads on focus, selects a full name without ID and clears advanced conditions", async () => {
    renderRequests();
    advanced();
    expect(api.models).not.toHaveBeenCalled();
    fireEvent.focus(model());
    fireEvent.click(
      await screen.findByRole("button", { name: "Provider / Available" }),
    );
    expect(model()).toHaveValue("Provider / Available");
    expect(api.page).toHaveBeenCalledTimes(1);
    applyFilters();
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        expect.objectContaining({
          model_name: "Provider / Available",
          model_id: undefined,
        }),
        expect.any(AbortSignal),
      ),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.clear_advanced" }),
    );
    expect(model()).toHaveValue("");
    expect(api.page).toHaveBeenCalledTimes(2);
  });
  it("deduplicates full names independently of model IDs and selects using the keyboard", async () => {
    api.models.mockResolvedValue({
      data: [
        { id: 1, name: "Provider / Same" },
        { id: 2, name: "Provider / Same" },
        { id: null, name: "" },
        { id: 3, name: null },
      ],
      total: 4,
    });
    renderRequests();
    advanced();
    fireEvent.focus(model());
    await screen.findByRole("option", { name: "Provider / Same" });
    expect(
      screen.getAllByRole("option", { name: "Provider / Same" }),
    ).toHaveLength(1);
    fireEvent.keyDown(model(), { key: "ArrowDown" });
    fireEvent.keyDown(model(), { key: "Enter" });
    expect(model()).toHaveValue("Provider / Same");
    expect(api.page).toHaveBeenCalledTimes(1);
  });
  it("retains manual exact historical names when the directory is unavailable", async () => {
    api.models.mockRejectedValue(new Error("unavailable"));
    renderRequests();
    advanced();
    fireEvent.focus(model());
    await screen.findByText("dsh.modelAuditView.modelLoadError");
    fireEvent.change(model(), { target: { value: " Provider / Deleted%_ " } });
    fireEvent.keyDown(model(), { key: "Escape" });
    applyFilters();
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        expect.objectContaining({ model_name: " Provider / Deleted%_ " }),
        expect.any(AbortSignal),
      ),
    );
  });
  it("paginates directory suggestions and filters remotely using the same input", async () => {
    api.models
      .mockResolvedValueOnce({ data: [{ id: 1, name: "One" }], total: 21 })
      .mockResolvedValueOnce({ data: [{ id: 2, name: "Two" }], total: 21 })
      .mockResolvedValue({ data: [], total: 0 });
    renderRequests();
    advanced();
    fireEvent.focus(model());
    await screen.findByRole("button", { name: "One" });
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.loadMoreModels" }),
    );
    await screen.findByRole("button", { name: "Two" });
    fireEvent.change(model(), { target: { value: "Missing" } });
    await screen.findByText("dsh.modelAuditView.noModels");
    expect(api.models).toHaveBeenLastCalledWith(
      expect.objectContaining({ keyword: "Missing", page: 1 }),
      expect.any(AbortSignal),
    );
    expect(api.page).toHaveBeenCalledTimes(1);
  });
  it("validates the half-open range and resets its applied query", async () => {
    renderRequests();
    await screen.findByText("dsh.modelAuditView.empty");
    fireEvent.click(screen.getByLabelText("dsh.modelAuditView.time_range"));
    fireEvent.change(
      screen.getByLabelText("dsh.modelAuditView.filters.start_at"),
      { target: { value: "2026-10-16T10:00" } },
    );
    fireEvent.change(
      screen.getByLabelText("dsh.modelAuditView.filters.end_at"),
      { target: { value: "2026-10-16T10:00" } },
    );
    applyFilters();
    expect(api.page).toHaveBeenCalledTimes(1);
    expect(
      screen.getByText("dsh.modelAuditView.invalid_time_range"),
    ).toBeVisible();
    fireEvent.change(
      screen.getByLabelText("dsh.modelAuditView.filters.end_at"),
      { target: { value: "2026-10-16T11:00" } },
    );
    applyFilters();
    await waitFor(() => expect(api.page).toHaveBeenCalledTimes(2));
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.resetFilters" }),
    );
    await waitFor(() => expect(api.page).toHaveBeenCalledTimes(3));
    expect(api.page.mock.calls.at(-1)?.[0].start_at).toBeUndefined();
    expect(api.page.mock.calls.at(-1)?.[0].end_at).toBeUndefined();
  });
  it("searches and paginates remotely, rejecting invalid IDs and stale results", async () => {
    let resolveOld: (value: AuditUserPage) => void = () => {};
    api.users.mockImplementation(async (query) => {
      if (query.keyword === "old")
        return new Promise((resolve) => {
          resolveOld = resolve;
        });
      if (query.keyword === "new")
        return { data: [{ user_id: 30, user_name: "New result" }], total: 1 };
      return {
        data:
          query.page === 1
            ? [
                { user_id: 20, user_name: "Alice" },
                { user_id: null, user_name: "Invalid" },
              ]
            : [{ user_id: 21, user_name: "Bob" }],
        total: 21,
      };
    });
    render(<ModelAuditRequests tenantId={2} initialView="unassociated" />);
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectUser" }),
    );
    await screen.findByRole("option", { name: "Alice" });
    expect(screen.queryByRole("option", { name: "Invalid" })).toBeNull();
    fireEvent.click(screen.getByRole("option", { name: "dsh.loadMoreUsers" }));
    await screen.findByRole("option", { name: "Bob" });
    expect(api.users).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2, tenant_id: 2 }),
      expect.any(AbortSignal),
    );
    fireEvent.change(screen.getByPlaceholderText("dsh.searchUsers"), {
      target: { value: "old" },
    });
    await waitFor(() =>
      expect(api.users).toHaveBeenLastCalledWith(
        expect.objectContaining({ keyword: "old", page: 1 }),
        expect.any(AbortSignal),
      ),
    );
    fireEvent.change(screen.getByPlaceholderText("dsh.searchUsers"), {
      target: { value: "new" },
    });
    await screen.findByRole("option", { name: "New result" });
    await act(async () =>
      resolveOld({
        data: [{ user_id: 99, user_name: "Old result" }],
        total: 1,
      }),
    );
    expect(screen.queryByRole("option", { name: "Old result" })).toBeNull();
  });

  it("clears the user and queries the newly selected tenant's user list", async () => {
    const value = {
      user: { tenant_id: 1, role: "admin", is_global_super: true },
    } as unknown as ContextType<typeof userContext>;
    render(
      <userContext.Provider value={value}>
        <ModelAuditPanel />
      </userContext.Provider>,
    );
    await screen.findByText("First tenant (first)");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "dsh.modelAuditView.selectUser" }));
    await user.click(await screen.findByRole("option", { name: "Alice" }));
    const signal = api.users.mock.calls[0][1] as AbortSignal;
    await user.click(screen.getByRole("combobox", { name: "dsh.modelAuditView.selectTenant" }));
    await user.click(await screen.findByRole("option", { name: "Second tenant (second)" }));
    expect(signal.aborted).toBe(true);
    await waitFor(() => expect(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectUser" }),
    ).toHaveTextContent("dsh.modelAuditView.allUsers"));
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        { tenant_id: 2, limit: 20 },
        expect.any(AbortSignal),
      ),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectUser" }),
    );
    await waitFor(() =>
      expect(api.users).toHaveBeenLastCalledWith(
        expect.objectContaining({ tenant_id: 2 }),
        expect.any(AbortSignal),
      ),
    );
  });

  it("supports retry and empty tenant user lists", async () => {
    api.users
      .mockRejectedValueOnce(new Error("unavailable"))
      .mockResolvedValueOnce({ data: [], total: 0 });
    render(<ModelAuditRequests tenantId={2} initialView="unassociated" />);
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectUser" }),
    );
    await screen.findByText("dsh.modelAuditView.userLoadError");
    fireEvent.click(screen.getByRole("option", { name: "dsh.refresh" }));
    await screen.findByText("dsh.modelAuditView.noUsers");
  });
});

// Coverage AC: AC-68.
describe("simplified audit layout keeps all advanced filters", () => {
  it("removes query explanations while preserving the seven advanced fields", async () => {
    renderRequests();
    await waitFor(() => expect(api.page).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "dsh.modelAuditView.query_info" })).toBeNull();
    expect(screen.queryByText("dsh.modelAuditView.scopeHint")).toBeNull();
    advanced();
    expect(screen.getByRole("combobox", { name: "dsh.modelAuditView.filters.model_name" })).toBeVisible();
    expect(await screen.findByRole("combobox", { name: "dsh.modelAuditView.summary_status" })).toBeVisible();
    for (const key of ["has_hit", "direction", "state"])
      expect(screen.getByRole("combobox", { name: "dsh.contentSafety.filters." + key })).toBeVisible();
    for (const key of ["request_id", "conversation_id"])
      expect(screen.getByLabelText("dsh.modelAuditView.filters." + key)).toBeVisible();
  });
});
