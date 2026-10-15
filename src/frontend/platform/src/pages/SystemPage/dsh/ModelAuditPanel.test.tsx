import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditBodyFrame, ModelAuditRecord } from "@/types/dshModelAudit";
import { userContext } from "@/contexts/userContext";
import type { ContextType } from "react";

const api = vi.hoisted(() => ({
  page: vi.fn(),
  body: vi.fn(),
  mode: vi.fn(),
  save: vi.fn(),
  detail: vi.fn(),
  tenants: vi.fn(),
}));
vi.mock("@/controllers/API/tenant", () => ({ getTenantsApi: api.tenants }));
vi.mock("@/controllers/API/dshModelAudit", () => ({
  getModelAudit: api.page,
  readAuditBody: api.body,
  getAuditMode: api.mode,
  saveAuditMode: api.save,
  getModelAuditDetail: api.detail,
}));
import { ModelAuditPanel, ModelAuditRequests } from "./ModelAuditPanel";
import { ModelAuditMode } from "./ModelAuditMode";
import { ModelAuditBody } from "./ModelAuditBody";
const record: ModelAuditRecord = {
  request_id: "one",
  user_id: 20,
  model_id: 42,
  model_name: "Synthetic",
  provider_name: "Synthetic",
  conversation_id: "conversation",
  request_kind: "chat",
  context_invalid: false,
  association_status: "ASSOCIATED",
  effective_mode: "CONTENT",
  started_at: "2026-10-14T10:00:00Z",
  last_write_at: null,
  input_units: 2,
  input_bytes: 10,
  output_bytes: 10,
  model_result: "SUCCEEDED",
  response_result: "INTERRUPTED",
  usage_settlement: "UNCERTAIN",
  content_status: "COMPLETE",
  usage: null,
};
beforeEach(() => {
  vi.clearAllMocks();
  api.tenants.mockReset();
  api.tenants.mockResolvedValue({
    data: [
      { id: 1, tenant_name: "First tenant", tenant_code: "first" },
      { id: 2, tenant_name: "Second tenant", tenant_code: "second" },
    ],
    total: 2,
  });
  api.page.mockResolvedValue({
    items: [record],
    next_cursor: "next",
    progress: { last_write_at: null },
  });
  api.mode.mockResolvedValue({ mode: "METADATA", version: 1 });
  api.body.mockImplementation(
    async function* (): AsyncGenerator<AuditBodyFrame> {
      yield {
        type: "meta",
        request_id: "one",
        encoding_version: 1,
        content_state: "COMPLETE",
      };
      yield {
        type: "part",
        seq: 0,
        channel: "input",
        unit_index: 0,
        fragment: "<img src=x onerror=alert(1)>private-original",
      };
      yield {
        type: "end",
        last_seq: 0,
        content_state: "COMPLETE",
        transfer_status: "COMPLETED",
      };
    },
  );
});

function renderPanel(globalAdmin = true, tenantId = 1) {
  const value = {
    user: {
      tenant_id: tenantId,
      role: globalAdmin ? "admin" : "user",
      is_global_super: globalAdmin,
      is_child_admin: !globalAdmin,
    },
  } as unknown as ContextType<typeof userContext>;
  return render(
    <userContext.Provider value={value}>
      <ModelAuditPanel />
    </userContext.Provider>,
  );
}

describe("audit tenant selection", () => {
  it("selects existing tenants by name and clears the previous tenant's originals", async () => {
    renderPanel();
    await screen.findByText("First tenant (first)");
    expect(screen.queryByLabelText("dsh.modelAuditView.tenant")).toBeNull();
    await screen.findByText("Synthetic");
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.original" }),
    );
    await screen.findByText(/private-original/);
    const oldSignal = api.page.mock.calls.at(-1)?.[1] as AbortSignal;
    fireEvent.keyDown(
      screen.getByRole("combobox", { name: "dsh.modelAuditView.selectTenant" }),
      { key: "ArrowDown" },
    );
    fireEvent.click(
      await screen.findByRole("option", { name: "Second tenant (second)" }),
    );
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        { tenant_id: 2, limit: 20 },
        expect.any(AbortSignal),
      ),
    );
    expect(oldSignal.aborted).toBe(true);
    expect(screen.queryByText(/private-original/)).toBeNull();
    expect(api.save).not.toHaveBeenCalled();
  });

  it("does not request audit data until an existing tenant is confirmed", async () => {
    api.tenants.mockReturnValue(new Promise(() => {}));
    renderPanel();
    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(api.mode).not.toHaveBeenCalled();
    expect(api.page).not.toHaveBeenCalled();
  });

  it("loads subsequent tenant pages and ignores invalid IDs", async () => {
    api.tenants
      .mockResolvedValueOnce({
        data: [{ id: null }, { id: "" }, { id: -1 }],
        total: 101,
      })
      .mockResolvedValueOnce({
        data: [{ id: 2, tenant_name: "Second tenant", tenant_code: "second" }],
        total: 101,
      });
    renderPanel();
    const selector = screen.getByRole("combobox");
    await waitFor(() => expect(selector).not.toBeDisabled());
    expect(api.tenants).toHaveBeenLastCalledWith({ page: 2, page_size: 100 });
    expect(api.page).not.toHaveBeenCalled();
    fireEvent.keyDown(selector, { key: "ArrowDown" });
    expect(await screen.findAllByRole("option")).toHaveLength(1);
    fireEvent.click(
      screen.getByRole("option", { name: "Second tenant (second)" }),
    );
    await waitFor(() =>
      expect(api.page).toHaveBeenCalledWith(
        { tenant_id: 2, limit: 20 },
        expect.any(AbortSignal),
      ),
    );
  });

  it("offers retry after loading fails and handles an empty list", async () => {
    api.tenants
      .mockRejectedValueOnce(new Error("unavailable"))
      .mockResolvedValueOnce({ data: [], total: 0 });
    renderPanel();
    await screen.findByRole("alert");
    expect(screen.getByRole("combobox")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "dsh.refresh" }));
    await screen.findByText("dsh.modelAuditView.noTenants");
    expect(api.page).not.toHaveBeenCalled();
    expect(api.mode).not.toHaveBeenCalled();
  });

  it("keeps tenant administrators scoped to their tenant without loading the global list", async () => {
    renderPanel(false, 2);
    await screen.findByText("Synthetic");
    expect(api.tenants).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("combobox", {
        name: "dsh.modelAuditView.selectTenant",
      }),
    ).toBeNull();
    expect(api.page).toHaveBeenCalledWith(
      { tenant_id: 2, limit: 20 },
      expect.any(AbortSignal),
    );
    expect(screen.queryByRole("button", { name: "dsh.save" })).toBeNull();
  });
});
describe("request-card audit UI", () => {
  it("renders bounded original segments without truncation or refetch", async () => {
    api.body.mockImplementation(
      async function* (): AsyncGenerator<AuditBodyFrame> {
        yield {
          type: "meta",
          request_id: "one",
          encoding_version: 1,
          content_state: "COMPLETE",
        };
        for (let index = 0; index < 1000; index++)
          yield {
            type: "part",
            seq: index,
            channel: "input",
            unit_index: index,
            fragment: "segment-fragment-" + index,
          };
        yield {
          type: "end",
          last_seq: 999,
          content_state: "COMPLETE",
          transfer_status: "COMPLETED",
        };
      },
    );
    const { container } = render(
      <ModelAuditBody requestId="one" tenantId={2} />,
    );
    await screen.findByText("dsh.modelAuditView.transfer.completed");
    expect(container.querySelectorAll("pre").length).toBeLessThanOrEqual(100);
    expect(screen.queryByText("segment-fragment-999")).toBeNull();
    for (let index = 0; index < 10; index++)
      fireEvent.click(screen.getByRole("button", { name: "dsh.next" }));
    await screen.findByText("segment-fragment-999");
    expect(container.querySelectorAll("pre").length).toBeLessThanOrEqual(100);
    expect(api.body).toHaveBeenCalledTimes(1);
  });
  it("shows evidence-based missing status instead of claiming no model call", async () => {
    api.page.mockResolvedValue({
      items: [],
      next_cursor: null,
      progress: { last_write_at: null },
    });
    api.detail.mockResolvedValue({
      request_id: "missing",
      audit_record_missing: true,
      gap: "MODE_UNKNOWN",
    });
    render(<ModelAuditRequests tenantId={2} />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "dsh.modelAuditView.advancedFilters",
      }),
    );
    fireEvent.change(
      screen.getByLabelText("dsh.modelAuditView.filters.request_id"),
      { target: { value: "missing" } },
    );
    await screen.findByText("dsh.modelAuditView.missing.MODE_UNKNOWN");
    expect(api.body).not.toHaveBeenCalled();
  });
  it("clears the exact-request filter when opening the full user conversation", async () => {
    render(<ModelAuditRequests tenantId={2} />);
    await screen.findByText("Synthetic");
    fireEvent.click(
      screen.getByRole("button", {
        name: "dsh.modelAuditView.advancedFilters",
      }),
    );
    fireEvent.change(
      screen.getByLabelText("dsh.modelAuditView.filters.request_id"),
      { target: { value: "one" } },
    );
    await screen.findByText("Synthetic");
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.timeline" }),
    );
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        {
          tenant_id: 2,
          limit: 20,
          user_id: 20,
          conversation_id: "conversation",
        },
        expect.any(AbortSignal),
      ),
    );
  });
  it("does not prefetch originals; explicitly opened originals render as text and clear on pagination", async () => {
    const { container } = render(<ModelAuditRequests tenantId={2} />);
    await screen.findByText("Synthetic");
    expect(api.body).not.toHaveBeenCalled();
    expect(screen.queryByText(/private-original/)).toBeNull();
    expect(
      screen.getByText("dsh.modelAuditView.states.INTERRUPTED"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("dsh.modelAuditView.states.COMPLETE"),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.original" }),
    );
    await screen.findByText(/private-original/);
    expect(container.querySelector("img")).toBeNull();
    expect(api.body).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "dsh.next" }));
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        expect.objectContaining({ cursor: "next", tenant_id: 2 }),
        expect.any(AbortSignal),
      ),
    );
    expect(screen.queryByText(/private-original/)).toBeNull();
  });
  it("cannot change modes when the tenant administrator is read-only", async () => {
    render(<ModelAuditMode tenantId={2} canConfigure={false} />);
    await waitFor(() => expect(screen.getByRole("combobox")).toBeDisabled());
    expect(screen.queryByRole("button", { name: "dsh.save" })).toBeNull();
    expect(api.save).not.toHaveBeenCalled();
  });
});
