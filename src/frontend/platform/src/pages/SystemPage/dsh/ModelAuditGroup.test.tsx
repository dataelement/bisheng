import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({
  groups: vi.fn(),
  requests: vi.fn(),
  groupRequests: vi.fn(),
  readiness: vi.fn(),
  tree: vi.fn(),
  body: vi.fn(),
}));
vi.mock("@/controllers/API/dshModelAudit", () => ({
  getAuditGroups: api.groups,
  getModelAudit: api.requests,
  getAuditGroupRequests: api.groupRequests,
  getAuditReadiness: api.readiness,
  getAuditTree: api.tree,
}));
vi.mock("./ModelAuditBody", () => ({
  ModelAuditBody: (p: unknown) => {
    api.body(p);
    return <p>Saved body</p>;
  },
}));
vi.mock("./ModelAuditParent", () => ({ ModelAuditParent: () => null }));
import { ModelAuditRequests } from "./ModelAuditPanel";
const ready = { status_ready: true, name_ready: true, indexing_pending: false };
const group = {
  conversation_key: "a".repeat(64),
  user_id: 20,
  user_name: "Audit Alice",
  conversation_id: "session-main",
  listed_at: "2026-10-15T12:00:00Z",
  last_request_at: "2026-10-15T12:08:00Z",
  updated_at: "2026-10-15T12:09:00Z",
  request_count: 21,
  abnormal_count: 1,
};
const record = {
  request_id: "request-one",
  user_id: 20,
  model_id: 42,
  model_name: "Provider / A",
  provider_name: "Provider",
  conversation_id: "session-main",
  request_kind: "compaction",
  context_invalid: false,
  association_status: "ASSOCIATED",
  effective_mode: "CONTENT",
  started_at: "2026-10-15T12:00:00Z",
  last_write_at: null,
  input_units: 2,
  input_bytes: 20,
  output_bytes: 10,
  model_result: "SUCCEEDED",
  response_result: "COMPLETED",
  usage_settlement: "SETTLED",
  content_status: "COMPLETE",
  usage: null,
  audit_status: "NORMAL",
  status_pending: false,
  status_reasons: [],
};
beforeEach(() => {
  vi.restoreAllMocks();
  vi.resetAllMocks();
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  api.readiness.mockResolvedValue(ready);
  api.groups.mockResolvedValue({
    items: [group],
    next_cursor: null,
    scan_limited: false,
    progress: ready,
  });
  api.groupRequests.mockResolvedValue({
    items: [record],
    next_cursor: "next-request",
    progress: { last_write_at: null },
  });
  api.requests.mockResolvedValue({
    items: [record],
    next_cursor: null,
    progress: { last_write_at: null },
  });
});
it("AC-QC-08: groups by default, expands metadata and reads only the explicitly opened original", async () => {
  render(<ModelAuditRequests tenantId={2} />);
  await screen.findByText(/session-main/);
  expect(
    screen.getByRole("button", { name: /Audit Alice.*session-main/ }),
  ).toBeVisible();
  expect(screen.queryByText(/#20/)).toBeNull();
  expect(api.requests).not.toHaveBeenCalled();
  expect(api.groupRequests).not.toHaveBeenCalled();
  expect(api.body).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /session-main/ }));
  await screen.findByText("Provider / A");
  expect(
    screen.queryByRole("button", { name: "dsh.modelAuditView.group_all" }),
  ).toBeNull();
  expect(api.groupRequests).toHaveBeenCalledTimes(1);
  expect(api.body).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "dsh.modelAuditView.original" }),
  );
  await screen.findByText("Saved body");
  expect(api.body).toHaveBeenCalledTimes(1);
  fireEvent.click(
    screen
      .getAllByRole("button", { name: "dsh.next" })
      .find((b) => !b.hasAttribute("disabled"))!,
  );
  await waitFor(() =>
    expect(api.groupRequests).toHaveBeenLastCalledWith(
      group.conversation_key,
      expect.objectContaining({ cursor: "next-request" }),
      expect.any(AbortSignal),
    ),
  );
  expect(screen.queryByText("Saved body")).toBeNull();
});
it("request cards do not offer redundant user or parent conversation navigation", async () => {
  render(<ModelAuditRequests tenantId={2} />);
  await screen.findByText(/session-main/);
  fireEvent.click(screen.getByRole("button", { name: /session-main/ }));
  await screen.findByText("Provider / A");
  expect(screen.queryByRole("button", { name: "dsh.modelAuditView.timeline" })).toBeNull();
  expect(screen.queryByRole("button", { name: "dsh.modelAuditView.sources.parent" })).toBeNull();
  expect(api.requests).not.toHaveBeenCalled();
  expect(
    screen.getByRole("radio", { name: "dsh.modelAuditView.views.groups" }),
  ).toHaveAttribute("aria-checked", "true");
});
it("AC-QC-06: unassociated requests use a separate exact query without loading all conversations", async () => {
  render(<ModelAuditRequests tenantId={2} />);
  await screen.findByText(/session-main/);
  fireEvent.click(
    screen.getByRole("radio", {
      name: "dsh.modelAuditView.views.unassociated",
    }),
  );
  await screen.findByText("Provider / A");
  expect(api.requests).toHaveBeenCalledWith(
    expect.objectContaining({ association_status: "UNASSOCIATED" }),
    expect.any(AbortSignal),
  );
  expect(api.groups).toHaveBeenCalledTimes(1);
  expect(api.body).not.toHaveBeenCalled();
});
it("AC-QC-10: empty scan batches and unready indexes do not claim that no logs exist", async () => {
  api.groups.mockResolvedValueOnce({
    items: [],
    next_cursor: "continue",
    scan_limited: true,
    progress: ready,
  });
  render(<ModelAuditRequests tenantId={2} />);
  await screen.findByText("dsh.modelAuditView.scan_limited");
  expect(screen.queryByText("dsh.modelAuditView.empty")).toBeNull();
  api.groups.mockResolvedValue({
    items: [],
    next_cursor: null,
    scan_limited: false,
    progress: { ...ready, status_ready: false },
  });
  fireEvent.click(screen.getByRole("button", { name: "dsh.next" }));
  await screen.findByText("dsh.modelAuditView.index_preparing");
  expect(screen.queryByText("dsh.modelAuditView.empty")).toBeNull();
});

it("AC-H07: publication during legacy pagination explicitly requires a refresh instead of reusing its cursor", async () => {
  api.readiness
    .mockResolvedValueOnce(ready)
    .mockResolvedValue({
      ...ready,
      hierarchy_available: true,
      hierarchy_ready: true,
      phase: "READY",
    });
  api.groups.mockResolvedValueOnce({
    items: [group],
    next_cursor: "legacy-next",
    scan_limited: false,
    progress: ready,
  });
  render(<ModelAuditRequests tenantId={2} />);
  await screen.findByRole("button", { name: /session-main/ });
  fireEvent.click(screen.getByRole("button", { name: "dsh.next" }));
  await screen.findByText("dsh.modelAuditView.tree.refresh_required");
  expect(api.tree).not.toHaveBeenCalled();
  expect(screen.queryByText("dsh.modelAuditView.empty")).toBeNull();
});
