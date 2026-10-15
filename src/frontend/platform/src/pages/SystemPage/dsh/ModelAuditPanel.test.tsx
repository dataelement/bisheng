import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditBodyFrame, ModelAuditRecord } from "@/types/dshModelAudit";

const api = vi.hoisted(() => ({
  page: vi.fn(),
  body: vi.fn(),
  mode: vi.fn(),
  save: vi.fn(),
  detail: vi.fn(),
}));
vi.mock("@/controllers/API/dshModelAudit", () => ({
  getModelAudit: api.page,
  readAuditBody: api.body,
  getAuditMode: api.mode,
  saveAuditMode: api.save,
  getModelAuditDetail: api.detail,
}));
import { ModelAuditRequests } from "./ModelAuditPanel";
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
