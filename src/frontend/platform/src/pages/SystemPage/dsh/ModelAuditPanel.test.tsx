import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
const management = vi.hoisted(() => ({
  scope: { scope_tenant_id: 1 as number | null, expires_at: null },
  loading: false,
  refresh: vi.fn(),
}));
vi.mock("@/hooks/useAdminScope", () => ({ useAdminScope: () => management }));
vi.mock("@/controllers/API/dshModelAudit", () => ({
  getModelAudit: api.page,
  getAuditReadiness: async () => ({
    status_ready: true,
    name_ready: true,
    indexing_pending: false,
  }),
  getAuditGroups: async (q: unknown, s: AbortSignal) => {
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
  },
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
  management.scope.scope_tenant_id = 1;
  management.loading = false;
  management.refresh.mockResolvedValue(undefined);
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
  api.body.mockImplementation(async function* (): AsyncGenerator<AuditBodyFrame> {
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
  });
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

describe("audit follows the shared management view", () => {
  it("uses the selected child tenant instead of Root or the administrator's home", async () => {
    management.scope.scope_tenant_id = 2;
    renderPanel(true, 1);
    await waitFor(() => expect(api.page).toHaveBeenCalledWith(
      { tenant_id: 2, limit: 20 }, expect.any(AbortSignal),
    ));
    expect(api.mode).toHaveBeenCalledWith(2, expect.any(AbortSignal));
    expect(api.tenants).not.toHaveBeenCalled();
    expect(screen.queryByRole("combobox", { name: "dsh.modelAuditView.selectTenant" })).toBeNull();
  });

  it("does not fall back to Root while management scope is loading or unavailable", async () => {
    management.scope.scope_tenant_id = null;
    management.loading = true;
    const view = renderPanel();
    expect(api.page).not.toHaveBeenCalled();
    expect(api.mode).not.toHaveBeenCalled();
    management.loading = false;
    view.rerender(<userContext.Provider value={{ user: { role: "admin", is_global_super: true } } as unknown as ContextType<typeof userContext>}><ModelAuditPanel /></userContext.Provider>);
    fireEvent.click(screen.getByRole("button", { name: "dsh.refresh" }));
    await waitFor(() => expect(management.refresh).toHaveBeenCalledOnce());
    expect(api.page).not.toHaveBeenCalled();
    expect(api.mode).not.toHaveBeenCalled();
  });

  it("clears originals and aborts the old tenant's requests on scope change", async () => {
    const value = { user: { user_id: 1, tenant_id: 1, role: "admin", is_global_super: true } } as unknown as ContextType<typeof userContext>;
    const content = () => <userContext.Provider value={value}><ModelAuditPanel /></userContext.Provider>;
    const view = render(content());
    fireEvent.click(screen.getByRole("radio", { name: "dsh.modelAuditView.views.unassociated" }));
    await screen.findByText("Synthetic");
    fireEvent.click(screen.getByRole("button", { name: "dsh.modelAuditView.original" }));
    await screen.findByText(/private-original/);
    const oldSignal = api.page.mock.calls.at(-1)?.[1] as AbortSignal;
    management.scope.scope_tenant_id = 2;
    view.rerender(content());
    expect(screen.queryByText(/private-original/)).toBeNull();
    expect(oldSignal.aborted).toBe(true);
    await waitFor(() => expect(api.page).toHaveBeenLastCalledWith(
      { tenant_id: 2, limit: 20 }, expect.any(AbortSignal),
    ));
    expect(api.save).not.toHaveBeenCalled();
  });

  it("discards late data from the previous tenant", async () => {
    let resolveOld!: (value: unknown) => void;
    api.page.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const value = { user: { tenant_id: 1, role: "admin", is_global_super: true } } as unknown as ContextType<typeof userContext>;
    const content = () => <userContext.Provider value={value}><ModelAuditPanel /></userContext.Provider>;
    const view = render(content());
    fireEvent.click(screen.getByRole("radio", { name: "dsh.modelAuditView.views.unassociated" }));
    management.scope.scope_tenant_id = 2;
    view.rerender(content());
    await act(async () => resolveOld({ items: [{ ...record, model_name: "Old tenant secret" }], next_cursor: null }));
    expect(screen.queryByText("Old tenant secret")).toBeNull();
  });

  it("uses a tenant administrator's home and keeps capture settings read-only", async () => {
    management.scope.scope_tenant_id = 1;
    renderPanel(false, 2);
    await waitFor(() => expect(api.page).toHaveBeenCalledWith(
      { tenant_id: 2, limit: 20 }, expect.any(AbortSignal),
    ));
    expect(api.mode).toHaveBeenCalledWith(2, expect.any(AbortSignal));
    expect(api.tenants).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "dsh.modelAuditView.configure" })).toBeNull();
  });
});
describe("request-card audit UI", () => {
  it("renders bounded original segments without truncation or refetch", async () => {
    api.body.mockImplementation(async function* (): AsyncGenerator<AuditBodyFrame> {
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
          fragment: JSON.stringify({
            role: "user",
            content: "segment-fragment-" + index,
          }),
        };
      yield {
        type: "end",
        last_seq: 999,
        content_state: "COMPLETE",
        transfer_status: "COMPLETED",
      };
    });
    const { container } = render(<ModelAuditBody requestId="one" tenantId={2} />);
    await screen.findByText("dsh.modelAuditView.transfer.completed");
    expect(container.querySelectorAll("article")).toHaveLength(100);
    expect(screen.getByText("segment-fragment-999")).toBeVisible();
    expect(screen.queryByText("segment-fragment-0")).toBeNull();
    const region = screen.getByRole("region", {
      name: "dsh.modelAuditView.message_content",
    });
    region.scrollTop = 200;
    for (let index = 0; index < 9; index++) fireEvent.click(screen.getByRole("button", { name: "pagination.next" }));
    await screen.findByText("segment-fragment-0");
    expect(screen.queryByText("segment-fragment-999")).toBeNull();
    expect(container.querySelectorAll("article")).toHaveLength(100);
    expect(api.body).toHaveBeenCalledTimes(1);
    expect(region.scrollTop).toBe(0);
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
    render(<ModelAuditRequests tenantId={2} initialView="unassociated" />);
    fireEvent.click(
      screen.getByRole("button", {
        name: "dsh.modelAuditView.advancedFilters",
      }),
    );
    fireEvent.change(screen.getByLabelText("dsh.modelAuditView.filters.request_id"), {
      target: { value: "missing" },
    });
    fireEvent.click(screen.getByRole("button", { name: "dsh.modelAuditView.search" }));
    await screen.findByText("dsh.modelAuditView.missing.MODE_UNKNOWN");
    expect(api.body).not.toHaveBeenCalled();
  });
  it("retains exact-request filtering without redundant user conversation navigation", async () => {
    render(<ModelAuditRequests tenantId={2} initialView="unassociated" />);
    if (!screen.queryByText("Synthetic"))
      fireEvent.click(
        screen.getByRole("radio", {
          name: "dsh.modelAuditView.views.unassociated",
        }),
      );
    await screen.findByText("Synthetic");
    fireEvent.click(
      screen.getByRole("button", {
        name: "dsh.modelAuditView.advancedFilters",
      }),
    );
    fireEvent.change(screen.getByLabelText("dsh.modelAuditView.filters.request_id"), {
      target: { value: "one" },
    });
    fireEvent.click(screen.getByRole("button", { name: "dsh.modelAuditView.search" }));
    if (!screen.queryByText("Synthetic"))
      fireEvent.click(
        screen.getByRole("radio", {
          name: "dsh.modelAuditView.views.unassociated",
        }),
      );
    await screen.findByText("Synthetic");
    expect(screen.queryByRole("button", { name: "dsh.modelAuditView.timeline" })).toBeNull();
    await waitFor(() =>
      expect(api.page).toHaveBeenLastCalledWith(
        {
          tenant_id: 2,
          limit: 20,
          request_id: "one",
          association_status: "UNASSOCIATED",
        },
        expect.any(AbortSignal),
      ),
    );
  });
  it("does not prefetch originals; explicitly opened originals render as text and clear on pagination", async () => {
    const { container } = render(<ModelAuditRequests tenantId={2} initialView="unassociated" />);
    if (!screen.queryByText("Synthetic"))
      fireEvent.click(
        screen.getByRole("radio", {
          name: "dsh.modelAuditView.views.unassociated",
        }),
      );
    await screen.findByText("Synthetic");
    expect(api.body).not.toHaveBeenCalled();
    expect(screen.queryByText(/private-original/)).toBeNull();
    fireEvent.click(
      screen.getByRole("button", {
        name: "dsh.modelAuditView.request_details",
      }),
    );
    expect(screen.getByText("dsh.modelAuditView.states.INTERRUPTED")).toBeInTheDocument();
    expect(screen.getByText("dsh.modelAuditView.states.COMPLETE")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "dsh.modelAuditView.original" }));
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
    await screen.findByText("dsh.modelAuditView.modes.METADATA");
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: "dsh.modelAuditView.configure" })).toBeNull();
    expect(screen.queryByRole("button", { name: "dsh.save" })).toBeNull();
    expect(api.save).not.toHaveBeenCalled();
  });
});
