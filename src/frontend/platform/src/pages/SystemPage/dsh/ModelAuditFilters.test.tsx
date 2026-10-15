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

beforeEach(() => {
  vi.resetAllMocks();
  api.models.mockResolvedValue({ data: ["Deleted model"], total: 1 });
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
  it("selects audited model names without requiring a live configuration and can clear the selection", async () => {
    render(<ModelAuditRequests tenantId={2} />);
    expect(api.models).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectModel" }),
    );
    fireEvent.click(
      await screen.findByRole("option", { name: "Deleted model" }),
    );
    expect(api.models).toHaveBeenCalledWith(
      { tenant_id: 2, page: 1, page_size: 20, keyword: undefined },
      expect.any(AbortSignal),
    );
    expect(
      screen.getByLabelText("dsh.modelAuditView.filters.model_name"),
    ).toHaveValue("Deleted model");
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        expect.objectContaining({ model_name: "Deleted model" }),
        expect.any(AbortSignal),
      ),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.selectModel" }),
    );
    fireEvent.click(
      screen.getByRole("option", { name: "dsh.modelAuditView.allModels" }),
    );
    expect(
      screen.getByLabelText("dsh.modelAuditView.filters.model_name"),
    ).toHaveValue("");
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        expect.objectContaining({ model_name: undefined }),
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
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        expect.objectContaining({ model_name: "Unavailable old model" }),
        expect.any(AbortSignal),
      ),
    );
  });

  it("paginates model suggestions, searches remotely and retries an empty response", async () => {
    api.models
      .mockResolvedValueOnce({ data: ["One"], total: 21 })
      .mockResolvedValueOnce({ data: ["Two"], total: 21 })
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
    fireEvent.change(model, { target: { value: "Synthetic" } });
    fireEvent.change(start, { target: { value: "2026-10-15T10:00" } });
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
    expect(
      screen.getByLabelText("dsh.modelAuditView.filters.start_at"),
    ).toBeTruthy();
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
