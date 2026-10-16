import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { userContext } from "@/contexts/userContext";
import type { ContextType } from "react";
import type { AuditUserPage } from "@/types/dshModelAudit";

const api = vi.hoisted(() => ({
  page: vi.fn(),
  users: vi.fn(),
  models: vi.fn(),
  mode: vi.fn(),
  tenants: vi.fn(),
}));
vi.mock("@/controllers/API/dshModelAudit", () => ({
  getModelAudit: api.page,
  getAuditUsers: api.users,
  getAuditModels: api.models,
  getAuditMode: api.mode,
}));
vi.mock("@/controllers/API/tenant", () => ({ getTenantsApi: api.tenants }));
import { ModelAuditPanel, ModelAuditRequests } from "./ModelAuditPanel";

function applyFilters() {
  fireEvent.click(
    screen.getByRole("button", { name: "dsh.modelAuditView.search" }),
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  api.models.mockResolvedValue({
    data: [{ id: 42, name: "Available model" }],
    total: 1,
  });
  api.page.mockResolvedValue({
    items: [],
    next_cursor: null,
    progress: { last_write_at: null },
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

describe("simplified audit filters", () => {
  it("keeps draft edits local, applies once, and refreshes only the applied query", async () => {
    render(<ModelAuditRequests tenantId={2} />);
    await screen.findByText("dsh.modelAuditView.empty");
    const model = screen.getByLabelText(
      "dsh.modelAuditView.filters.model_name",
    );
    fireEvent.change(model, { target: { value: "Applied model" } });
    expect(screen.getByText("dsh.modelAuditView.pending_filters")).toBeVisible();
    expect(api.page).toHaveBeenCalledTimes(1);
    expect(api.models).not.toHaveBeenCalled();
    applyFilters();
    await waitFor(() => expect(api.page).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("dsh.modelAuditView.pending_filters")).toBeNull();
    await screen.findByText("dsh.modelAuditView.empty");
    fireEvent.change(model, { target: { value: "Unsaved draft" } });
    expect(api.page).toHaveBeenCalledTimes(2);
    fireEvent.click(
      screen.getByRole("button", {
        name: "dsh.modelAuditView.refresh_records",
      }),
    );
    await waitFor(() => expect(api.page).toHaveBeenCalledTimes(3));
    expect(api.page).toHaveBeenLastCalledWith(
      expect.objectContaining({ model_name: "Applied model" }),
      expect.any(AbortSignal),
    );
    expect(model).toHaveValue("Unsaved draft");
  });

  it("validates the half-open time interval before searching and restores trigger focus", async () => {
    render(<ModelAuditRequests tenantId={2} />);
    await screen.findByText("dsh.modelAuditView.empty");
    const trigger = screen.getByLabelText("dsh.modelAuditView.time_range");
    fireEvent.click(trigger);
    const start = screen.getByLabelText("dsh.modelAuditView.filters.start_at");
    const end = screen.getByLabelText("dsh.modelAuditView.filters.end_at");
    fireEvent.change(start, { target: { value: "2026-10-16T10:00" } });
    fireEvent.change(end, { target: { value: "2026-10-16T10:00" } });
    applyFilters();
    expect(api.page).toHaveBeenCalledTimes(1);
    expect(
      screen.getByText("dsh.modelAuditView.invalid_time_range"),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "dsh.modelAuditView.confirm_time" }),
    ).toBeDisabled();
    fireEvent.change(end, { target: { value: "2026-10-16T11:00" } });
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.confirm_time" }),
    );
    expect(trigger).toHaveFocus();
    expect(start).not.toBeVisible();
    expect(api.page).toHaveBeenCalledTimes(1);
    applyFilters();
    await waitFor(() => expect(api.page).toHaveBeenCalledTimes(2));
    expect(api.page).toHaveBeenLastCalledWith(
      expect.objectContaining({
        start_at: new Date("2026-10-16T10:00").toISOString(),
        end_at: new Date("2026-10-16T11:00").toISOString(),
      }),
      expect.any(AbortSignal),
    );
    fireEvent.click(trigger);
    fireEvent.keyDown(end, { key: "Escape" });
    expect(start).not.toBeVisible();
    expect(trigger).toHaveFocus();
    fireEvent.click(trigger);
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.clear_time" }),
    );
    expect(start).toHaveValue("");
    expect(end).toHaveValue("");
    fireEvent.pointerDown(document.body);
    expect(start).not.toBeVisible();
  });

  it("clears advanced draft conditions without changing common filters or querying", async () => {
    render(<ModelAuditRequests tenantId={2} />);
    await screen.findByText("dsh.modelAuditView.empty");
    fireEvent.change(
      screen.getByLabelText("dsh.modelAuditView.filters.model_name"),
      { target: { value: "Exact model" } },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "dsh.modelAuditView.advancedFilters",
      }),
    );
    fireEvent.change(
      screen.getByLabelText("dsh.modelAuditView.filters.request_id"),
      { target: { value: "request" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.clear_advanced" }),
    );
    expect(
      screen.getByLabelText("dsh.modelAuditView.filters.request_id"),
    ).toHaveValue("");
    expect(
      screen.getByLabelText("dsh.modelAuditView.filters.model_name"),
    ).toHaveValue("Exact model");
    expect(api.page).toHaveBeenCalledTimes(1);
  });

  it("clears a selected model ID when typing an exact historical name and resets both filters", async () => {
    render(<ModelAuditRequests tenantId={2} />);
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectModel" }),
    );
    fireEvent.click(
      await screen.findByRole("option", { name: "Available model" }),
    );
    applyFilters();
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        expect.objectContaining({ model_id: 42, model_name: undefined }),
        expect.any(AbortSignal),
      ),
    );
    const input = screen.getByLabelText(
      "dsh.modelAuditView.filters.model_name",
    );
    fireEvent.change(input, { target: { value: "Provider / Deleted model" } });
    applyFilters();
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        expect.objectContaining({
          model_id: undefined,
          model_name: "Provider / Deleted model",
        }),
        expect.any(AbortSignal),
      ),
    );
    expect(input).toHaveValue("Provider / Deleted model");
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.resetFilters" }),
    );
    expect(input).toHaveValue("");
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        { tenant_id: 2, limit: 20 },
        expect.any(AbortSignal),
      ),
    );
  });

  it("keeps same-name models distinct by ID and ignores invalid model candidates", async () => {
    api.models.mockResolvedValue({
      data: [
        { id: null, name: "Invalid" },
        { id: "", name: "Invalid" },
        { id: 42, name: "Same name" },
        { id: 43, name: "Same name" },
      ],
      total: 4,
    });
    render(<ModelAuditRequests tenantId={2} />);
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectModel" }),
    );
    const options = await screen.findAllByRole("option", { name: "Same name" });
    expect(options).toHaveLength(2);
    expect(screen.queryByRole("option", { name: "Invalid" })).toBeNull();
    fireEvent.click(options[1]);
    applyFilters();
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        expect.objectContaining({ model_id: 43, model_name: undefined }),
        expect.any(AbortSignal),
      ),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.resetFilters" }),
    );
    expect(
      screen.getByLabelText("dsh.modelAuditView.filters.model_name"),
    ).toHaveValue("");
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        { tenant_id: 2, limit: 20 },
        expect.any(AbortSignal),
      ),
    );
  });

  it("selects an available model by ID and can clear the selection", async () => {
    render(<ModelAuditRequests tenantId={2} />);
    expect(api.models).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectModel" }),
    );
    fireEvent.click(
      await screen.findByRole("option", { name: "Available model" }),
    );
    applyFilters();
    expect(api.models).toHaveBeenCalledWith(
      { tenant_id: 2, page: 1, page_size: 20, keyword: undefined },
      expect.any(AbortSignal),
    );
    expect(
      screen.getByLabelText("dsh.modelAuditView.filters.model_name"),
    ).toHaveValue("Available model");
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        expect.objectContaining({ model_id: 42, model_name: undefined }),
        expect.any(AbortSignal),
      ),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectModel" }),
    );
    fireEvent.click(
      screen.getByRole("option", { name: "dsh.modelAuditView.allModels" }),
    );
    applyFilters();
    expect(
      screen.getByLabelText("dsh.modelAuditView.filters.model_name"),
    ).toHaveValue("");
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        expect.objectContaining({ model_id: undefined, model_name: undefined }),
        expect.any(AbortSignal),
      ),
    );
  });

  it("keeps manual historical-name entry available if model suggestions fail", async () => {
    api.models.mockRejectedValueOnce(new Error("unavailable"));
    render(<ModelAuditRequests tenantId={2} />);
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectModel" }),
    );
    await screen.findByText("dsh.modelAuditView.modelLoadError");
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectModel" }),
    );
    fireEvent.change(
      screen.getByLabelText("dsh.modelAuditView.filters.model_name"),
      { target: { value: "Unavailable old model" } },
    );
    applyFilters();
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        expect.objectContaining({ model_name: "Unavailable old model" }),
        expect.any(AbortSignal),
      ),
    );
  });

  it("paginates model suggestions, searches remotely and retries an empty response", async () => {
    api.models
      .mockResolvedValueOnce({ data: [{ id: 1, name: "One" }], total: 21 })
      .mockResolvedValueOnce({ data: [{ id: 2, name: "Two" }], total: 21 })
      .mockResolvedValueOnce({ data: [], total: 0 });
    render(<ModelAuditRequests tenantId={2} />);
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectModel" }),
    );
    fireEvent.click(
      await screen.findByRole("option", {
        name: "dsh.modelAuditView.loadMoreModels",
      }),
    );
    await screen.findByRole("option", { name: "Two" });
    expect(api.models).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2, tenant_id: 2 }),
      expect.any(AbortSignal),
    );
    fireEvent.change(
      screen.getByPlaceholderText("dsh.modelAuditView.searchModels"),
      { target: { value: "missing" } },
    );
    await screen.findByText("dsh.modelAuditView.noModels");
    expect(api.models).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1, keyword: "missing" }),
      expect.any(AbortSignal),
    );
  });

  it("combines common filters and resets both their query and visible values", async () => {
    render(<ModelAuditRequests tenantId={2} />);
    const model = screen.getByLabelText(
      "dsh.modelAuditView.filters.model_name",
    );
    const start = screen.getByLabelText("dsh.modelAuditView.filters.start_at");
    fireEvent.click(screen.getByText("dsh.modelAuditView.all_time"));
    fireEvent.change(model, { target: { value: "Synthetic" } });
    fireEvent.change(start, { target: { value: "2026-10-15T10:00" } });
    applyFilters();
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        expect.objectContaining({
          tenant_id: 2,
          model_name: "Synthetic",
          start_at: new Date("2026-10-15T10:00").toISOString(),
        }),
        expect.any(AbortSignal),
      ),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.resetFilters" }),
    );
    expect(model).toHaveValue("");
    expect(start).toHaveValue("");
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        { tenant_id: 2, limit: 20 },
        expect.any(AbortSignal),
      ),
    );
  });

  it("keeps only common filters visible and shows the count of active hidden debug filters", async () => {
    render(<ModelAuditRequests tenantId={2} />);
    await screen.findByText("dsh.modelAuditView.empty");
    expect(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectUser" }),
    ).toBeTruthy();
    expect(
      screen.getByLabelText("dsh.modelAuditView.filters.model_name"),
    ).toBeTruthy();
    expect(screen.getByText("dsh.modelAuditView.all_time")).toBeTruthy();
    expect(
      screen.getByLabelText("dsh.modelAuditView.filters.start_at"),
    ).not.toBeVisible();
    expect(
      screen.queryByLabelText("dsh.modelAuditView.filters.user_keyword"),
    ).toBeNull();
    expect(screen.queryByLabelText("dsh.modelAuditView.user")).toBeNull();
    expect(
      screen.queryByLabelText("dsh.modelAuditView.filters.request_id"),
    ).toBeNull();
    expect(
      screen.queryByRole("combobox", {
        name: "dsh.modelAuditView.axes.model_result",
      }),
    ).toBeNull();
    const advanced = screen.getByRole("button", {
      name: "dsh.modelAuditView.advancedFilters",
    });
    expect(advanced).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(advanced);
    fireEvent.change(
      screen.getByLabelText("dsh.modelAuditView.filters.provider_name"),
      { target: { value: "provider" } },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: /dsh.modelAuditView.advancedFilters/,
      }),
    );
    expect(
      screen.queryByLabelText("dsh.modelAuditView.filters.provider_name"),
    ).toBeNull();
    expect(
      screen.getByRole("button", {
        name: "dsh.modelAuditView.advancedFilters (1)",
      }),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.resetFilters" }),
    );
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        { tenant_id: 2, limit: 20 },
        expect.any(AbortSignal),
      ),
    );
  });

  it("loads tenant users on demand, selects by name and can return to all users", async () => {
    render(<ModelAuditRequests tenantId={2} />);
    expect(api.users).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectUser" }),
    );
    fireEvent.click(await screen.findByRole("option", { name: "Alice" }));
    applyFilters();
    expect(api.users).toHaveBeenCalledWith(
      { tenant_id: 2, page: 1, page_size: 20, keyword: undefined },
      expect.any(AbortSignal),
    );
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        expect.objectContaining({ tenant_id: 2, user_id: 20 }),
        expect.any(AbortSignal),
      ),
    );
    expect(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectUser" }),
    ).toHaveTextContent("Alice");
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectUser" }),
    );
    fireEvent.click(
      screen.getByRole("option", { name: "dsh.modelAuditView.allUsers" }),
    );
    applyFilters();
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        expect.objectContaining({ user_id: undefined }),
        expect.any(AbortSignal),
      ),
    );
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
    render(<ModelAuditRequests tenantId={2} />);
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
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectUser" }),
    );
    fireEvent.click(await screen.findByRole("option", { name: "Alice" }));
    const signal = api.users.mock.calls[0][1] as AbortSignal;
    fireEvent.keyDown(
      screen.getByRole("combobox", { name: "dsh.modelAuditView.selectTenant" }),
      { key: "ArrowDown" },
    );
    fireEvent.click(
      await screen.findByRole("option", { name: "Second tenant (second)" }),
    );
    expect(signal.aborted).toBe(true);
    expect(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectUser" }),
    ).toHaveTextContent("dsh.modelAuditView.allUsers");
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
    render(<ModelAuditRequests tenantId={2} />);
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectUser" }),
    );
    await screen.findByText("dsh.modelAuditView.userLoadError");
    fireEvent.click(screen.getByRole("option", { name: "dsh.refresh" }));
    await screen.findByText("dsh.modelAuditView.noUsers");
  });
});
