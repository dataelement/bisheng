import * as React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { userContext } from "@/contexts/userContext";
import { contentSafetyStates } from "@/types/dshContentSafety";
import type { ContentSafetyEventMetadata, ContentSafetyEventPage } from "@/types/dshContentSafety";
import type { ModelAuditQuery, ModelAuditRecord } from "@/types/dshModelAudit";
import { ContentSafetyDetails, ContentSafetyEventDetails } from "./ContentSafetyDetails";
import { ModelAuditCard } from "./ModelAuditCard";
import { ModelAuditFilters } from "./ModelAuditFilters";
import { ModelAuditModelSelect } from "./ModelAuditModelSelect";
import { ModelAuditRequests } from "./ModelAuditPanel";
import { UnassociatedSafetyEvents } from "./UnassociatedSafetyEvents";
import en from "../../../../public/locales/en-US/bs.json";
import zh from "../../../../public/locales/zh-Hans/bs.json";
import ja from "../../../../public/locales/ja/bs.json";

const api = vi.hoisted(() => ({
  events: vi.fn(),
  unassociated: vi.fn(),
  page: vi.fn(),
  readiness: vi.fn(),
  groups: vi.fn(),
  tree: vi.fn(),
  groupRequests: vi.fn(),
  users: vi.fn(),
  models: vi.fn(),
  body: vi.fn(),
}));
vi.mock("@/controllers/API/dshContentSafety", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/controllers/API/dshContentSafety")>()),
  getAuditSafetyEvents: api.events,
  getUnassociatedSafetyEvents: api.unassociated,
}));
vi.mock("@/controllers/API/dshModelAudit", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/controllers/API/dshModelAudit")>()),
  getModelAudit: api.page,
  getAuditReadiness: api.readiness,
  getAuditGroups: api.groups,
  getAuditTree: api.tree,
  getAuditGroupRequests: api.groupRequests,
  getAuditUsers: api.users,
  getAuditModels: api.models,
  readAuditBody: api.body,
}));
const row: ModelAuditRecord = {
  request_id: "request-1",
  user_id: 11,
  model_id: 7,
  model_name: "Synthetic model",
  provider_name: "Provider",
  conversation_id: null,
  request_kind: "chat",
  context_invalid: false,
  association_status: "ASSOCIATED",
  effective_mode: "CONTENT",
  started_at: "2026-01-01T00:00:00Z",
  last_write_at: null,
  input_units: 1,
  input_bytes: 10,
  output_bytes: 20,
  model_result: "SUCCEEDED",
  response_result: "COMPLETED",
  usage_settlement: "SETTLED",
  content_status: "COMPLETE",
  usage: null,
  audit_status: "NORMAL",
};
const event: ContentSafetyEventMetadata = {
  schema_version: 1,
  source_id: "source-a",
  event_id: "11111111-1111-4111-8111-111111111111",
  gateway_request_id: "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
  backend_request_id: null,
  user_id: "9007199254740993",
  model_id: "9223372036854775807",
  session_id: null,
  protocol: "RESPONSES",
  event_kind: "FINAL",
  event_version: 2,
  request_started_at: "2026-01-01T00:00:00Z",
  occurred_at: "2026-02-01T00:00:00Z",
  received_at: "2026-03-01T00:00:00Z",
  stage_results: { input: "PASSED", output: "BLOCKED" },
  stage_versions: { input: 1, output: 2 },
  policy_version: 0,
  builtin_digest: "a".repeat(64),
  hit_count: 20,
  hit_count_truncated: true,
  rule_refs: ["<script>synthetic</script>"],
  forwarded: true,
  drain_status: "FINISHED",
  conversation: null,
  association_status: "UNASSOCIATED",
  audit_request_id: null,
};
const ready = {
  status_ready: true,
  name_ready: true,
  indexing_pending: false,
  safety_ready: true,
  safety_summary_version: 0,
  safety_summary_as_of: event.received_at,
};
const group = {
  conversation_key: "a".repeat(64),
  conversation_id: "Synthetic group",
  user_id: 11,
  user_name: "Synthetic user",
  listed_at: event.request_started_at,
  last_request_at: event.request_started_at,
  updated_at: event.request_started_at,
  request_count: 4,
  abnormal_count: 0,
  sensitive_hit_count: 2,
};
const page = (
  items: ContentSafetyEventMetadata[] = [event],
  next_cursor: string | null = null,
  details_status: ContentSafetyEventPage["details_status"] = "AVAILABLE",
): ContentSafetyEventPage => ({ items, next_cursor, details_status });
const button = (name: string) => screen.getByRole("button", { name });
const search = () => fireEvent.click(button("dsh.modelAuditView.search"));
const enterEvents = () => fireEvent.click(button("dsh.contentSafety.association.unassociated_title"));
const labels = {
  user: "dsh.modelAuditView.user",
  model: "dsh.auditHistory.fields.model_id",
  gateway: "dsh.contentSafety.details.gateway_request_id",
  backend: "dsh.contentSafety.details.backend_request_id",
  start: "dsh.modelAuditView.filters.start_at",
  end: "dsh.modelAuditView.filters.end_at",
};
const change = (key: keyof typeof labels, value: string) =>
  fireEvent.change(screen.getByLabelText(labels[key]), { target: { value } });
function card(extra: Partial<ModelAuditRecord> = {}, expanded = false) {
  return render(
    <ModelAuditCard
      row={{ ...row, ...extra }}
      tenantId={101}
      expanded={expanded}
      onToggle={vi.fn()}
      onNavigate={vi.fn()}
    />,
  );
}
function filterForm(initial: ModelAuditQuery = { limit: 20, cursor: "old-page" }) {
  const apply = vi.fn();
  function Harness() {
    const [draft, setDraft] = React.useState(initial);
    return (
      <ModelAuditFilters
        tenantId={101}
        pending={false}
        statusReady
        nameReady
        draft={draft}
        onChange={(changes) => setDraft((old) => ({ ...old, ...changes }))}
        onApply={() => apply(draft)}
        onReset={() => setDraft({ limit: 20 })}
      />
    );
  }
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: /^dsh.modelAuditView.advancedFilters/ }));
  return apply;
}
function choose(key: string, value: string) {
  fireEvent.keyDown(screen.getByRole("combobox", { name: "dsh.contentSafety.filters." + key }), { key: "ArrowDown" });
  fireEvent.click(screen.getByRole("option", { name: value }));
}
afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  api.events.mockResolvedValue(page([], null, "UNREPORTED"));
  api.unassociated.mockResolvedValue(page());
  api.page.mockResolvedValue({ items: [row], next_cursor: null, progress: ready });
  api.readiness.mockResolvedValue(ready);
  api.groups.mockResolvedValue({ items: [group], next_cursor: null, scan_limited: false, progress: ready });
  api.tree.mockResolvedValue({ items: [], next_cursor: null, scan_limited: false, progress: ready });
  api.groupRequests.mockResolvedValue({ items: [], next_cursor: null, progress: ready });
  api.users.mockResolvedValue({ data: [], total: 0 });
  api.models.mockResolvedValue({ data: [], total: 0 });
});

// Coverage AC: AC-34, AC-44, AC-46, AC-51, AC-56.
describe("independent safety, model and retained-detail facts", () => {
  it.each(["", "   "])("shows the known model ID when an external audit has no model name: %j", (name) => {
    card({ model_name: name, model_id: 271828, record_origin: "EXTERNAL_SAFETY", model_entered: false });
    expect(screen.getByTitle("dsh.auditHistory.fields.model_id: 271828")).toBeVisible();
    fireEvent.click(button("dsh.modelAuditView.request_details"));
    expect(screen.getAllByText("dsh.auditHistory.fields.model_id: 271828")).toHaveLength(2);
    expect(api.body).not.toHaveBeenCalled();
  });
  it.each(contentSafetyStates)("shows %s independently for summary and both stages", (state) => {
    card({ content_safety_state: state, stage_results: { input: state, output: state } });
    for (const stage of ["summary", "input", "output"])
      expect(
        screen.getByText("dsh.contentSafety.details." + stage + ": dsh.contentSafety.states." + state),
      ).toBeVisible();
    expect(screen.getByRole("article").querySelectorAll(".text-caption")).toHaveLength(3);
  });
  it("preserves model success and actual metering alongside an output hit", () => {
    card({
      content_safety_state: "BLOCKED",
      stage_results: { input: "PASSED", output: "BLOCKED" },
      usage: { input_tokens: 1, output_tokens: 2, total_tokens: 3, status: "SETTLED" },
    });
    fireEvent.click(button("dsh.modelAuditView.request_details"));
    expect(screen.getByText("dsh.modelAuditView.states.SUCCEEDED")).toBeVisible();
    expect(screen.getByText("3")).toBeVisible();
    expect(screen.getByText("dsh.contentSafety.details.output: dsh.contentSafety.states.BLOCKED")).toBeVisible();
    expect(api.events).not.toHaveBeenCalled();
  });
  it("renders missing legacy fields as unreported and unknown usage, never pass or zero", () => {
    card();
    expect(screen.getAllByText(/dsh.contentSafety.states.UNREPORTED/)).toHaveLength(3);
    expect(screen.getByText("dsh.modelAuditView.unknown")).toBeVisible();
    expect(screen.queryByText("0")).toBeNull();
    expect(screen.queryByText(/dsh.contentSafety.states.PASSED/)).toBeNull();
  });
  it.each([
    { record_origin: "EXTERNAL_SAFETY", model_entered: false },
    { record_origin: "EXTERNAL_SAFETY", model_entered: null },
    { record_origin: "MODEL", model_entered: false },
  ] as const)("never requests nonexistent original model content: %j", (extra) => {
    card(extra, true);
    expect(screen.queryByRole("button", { name: "dsh.modelAuditView.collapse" })).toBeNull();
    expect(api.body).not.toHaveBeenCalled();
  });
  it("loads details only on demand and retains a known hit after detail cleanup", async () => {
    api.events.mockResolvedValue(page([], null, "UNREPORTED"));
    card({
      content_safety_state: "BLOCKED",
      stage_results: { input: "BLOCKED", output: "NOT_APPLICABLE" },
      details_status: "PURGED",
      effective_mode: "METADATA",
      content_status: "NOT_CAPTURED",
    });
    expect(button("dsh.modelAuditView.original")).toBeDisabled();
    expect(api.events).not.toHaveBeenCalled();
    fireEvent.click(button("dsh.contentSafety.actions.view_details"));
    await screen.findByText("dsh.contentSafety.details_status.PURGED");
    await screen.findByText("dsh.contentSafety.details.empty");
    expect(screen.getByText("dsh.contentSafety.details.summary: dsh.contentSafety.states.BLOCKED")).toBeVisible();
    expect(api.body).not.toHaveBeenCalled();
  });
  it.each(["PENDING", "UNREPORTED", "PURGED"] as const)("keeps %s distinct from a passed check", async (status) => {
    api.events.mockResolvedValue(page([], null, status));
    render(<ContentSafetyDetails requestId={row.request_id} tenantId={101} />);
    await screen.findByText("dsh.contentSafety.details_status." + status);
    expect(screen.queryByText(/states.PASSED/)).toBeNull();
  });
  it("displays distinct observation times and bounded escaped rule references without billing claims", () => {
    render(<ContentSafetyEventDetails event={event} />);
    expect(screen.getByText("<script>synthetic</script>")).toBeVisible();
    expect(document.querySelector("script")).toBeNull();
    for (const key of ["request_started_at", "occurred_at", "received_at", "hit_count_truncated"])
      expect(screen.getByText("dsh.contentSafety.details." + key)).toBeVisible();
    expect(screen.getByText("dsh.contentSafety.drain.usage_hint")).toBeVisible();
    expect(screen.getByText("dsh.contentSafety.details.unknown")).toBeVisible();
  });
  it("retains earlier events after next-page failure and retries exactly that cursor", async () => {
    api.events
      .mockResolvedValueOnce(page([event], "page2"))
      .mockRejectedValueOnce(Error("synthetic private SQL"))
      .mockResolvedValueOnce(page([{ ...event, event_id: "second" }]));
    render(<ContentSafetyDetails requestId={row.request_id} tenantId={101} />);
    fireEvent.click(await screen.findByRole("button", { name: "dsh.contentSafety.actions.load_more" }));
    await screen.findByRole("alert");
    expect(screen.getByText(event.event_id)).toBeVisible();
    expect(screen.queryByText("synthetic private SQL")).toBeNull();
    fireEvent.click(button("dsh.contentSafety.actions.retry"));
    await screen.findByText("second");
    expect(api.events.mock.calls.slice(1).every((call) => call[1].cursor === "page2")).toBe(true);
    expect(screen.getByText(event.event_id)).toBeVisible();
  });
  it("retries failed refresh from the first page, not the stale next cursor", async () => {
    api.events
      .mockResolvedValueOnce(page([event], "stale-next"))
      .mockRejectedValueOnce(Error("offline"))
      .mockResolvedValueOnce(page([{ ...event, event_id: "fresh" }], "new-next"));
    render(<ContentSafetyDetails requestId={row.request_id} tenantId={101} />);
    await screen.findByText(event.event_id);
    fireEvent.click(button("dsh.contentSafety.actions.refresh"));
    await screen.findByRole("alert");
    fireEvent.click(button("dsh.contentSafety.actions.retry"));
    await screen.findByText("fresh");
    expect(api.events).toHaveBeenLastCalledWith(
      row.request_id,
      { tenant_id: 101, cursor: undefined, limit: 20 },
      expect.any(AbortSignal),
    );
    expect(screen.queryByText(event.event_id)).toBeNull();
  });
  it("aborts old request scope and ignores a late old-tenant detail response", async () => {
    let finish!: (value: ContentSafetyEventPage) => void;
    api.events
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValue(page([], null, "PENDING"));
    const view = render(<ContentSafetyDetails requestId="old" tenantId={101} />);
    const signal = api.events.mock.calls[0][2] as AbortSignal;
    view.rerender(<ContentSafetyDetails requestId="new" tenantId={202} />);
    await screen.findByText("dsh.contentSafety.details_status.PENDING");
    expect(signal.aborted).toBe(true);
    await act(async () => finish(page()));
    expect(screen.queryByText(event.event_id)).toBeNull();
  });
});

// Coverage AC: AC-45, AC-49, AC-56.
describe("real audit filters and explicit cursor invalidation", () => {
  it("combines no known hit, BOTH intersection and unreported without auto-applying", () => {
    const apply = filterForm();
    choose("has_hit", "dsh.contentSafety.filters.no_known_hit");
    choose("direction", "dsh.contentSafety.directions.BOTH");
    choose("state", "dsh.contentSafety.states.UNREPORTED");
    expect(apply).not.toHaveBeenCalled();
    expect(screen.getByText("dsh.contentSafety.filters.no_known_hit_hint")).toBeVisible();
    search();
    expect(apply).toHaveBeenCalledWith(
      expect.objectContaining({
        has_sensitive_hit: false,
        sensitive_direction: "BOTH",
        content_safety_state: "UNREPORTED",
        cursor: undefined,
      }),
    );
    expect(en.dsh.contentSafety.directions.BOTH).toBe("Both input and output matched");
    expect(zh.dsh.contentSafety.directions.BOTH).toContain(String.fromCodePoint(0x5747));
    expect(ja.dsh.contentSafety.directions.BOTH).toContain(String.fromCodePoint(0x4e21, 0x65b9));
  });
  it("offers all six safety states and clearing conditions preserves implicit date defaults", () => {
    const apply = filterForm({ limit: 20, content_safety_state: "BLOCKED", sensitive_direction: "BOTH" });
    fireEvent.keyDown(screen.getByRole("combobox", { name: "dsh.contentSafety.filters.state" }), { key: "ArrowDown" });
    for (const state of contentSafetyStates)
      expect(screen.getByRole("option", { name: "dsh.contentSafety.states." + state })).toBeVisible();
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "Escape" });
    fireEvent.click(button("dsh.modelAuditView.clear_advanced"));
    search();
    expect(apply).toHaveBeenCalledWith(
      expect.objectContaining({ sensitive_direction: undefined, content_safety_state: undefined }),
    );
    expect(apply.mock.calls[0][0].start_at).toBeUndefined();
    expect(apply.mock.calls[0][0].end_at).toBeUndefined();
  });
  it("filters malformed empty user IDs without a blank selector crash", async () => {
    api.users.mockResolvedValue({
      data: [
        { user_id: null, user_name: "Invalid null" },
        { user_id: "", user_name: "Invalid empty" },
        { user_id: 11, user_name: "Valid user" },
      ],
      total: 3,
    });
    api.models.mockResolvedValue({
      data: [
        { id: null, name: null },
        { id: "", name: "" },
        { id: 7, name: "Valid model" },
      ],
      total: 3,
    });
    filterForm();
    fireEvent.click(button("dsh.modelAuditView.selectUser"));
    expect(await screen.findByRole("option", { name: "Valid user" })).toBeVisible();
    expect(screen.queryByRole("option", { name: "Invalid empty" })).toBeNull();
    expect(screen.queryByRole("option", { name: "Invalid null" })).toBeNull();
    fireEvent.click(screen.getByRole("option", { name: "Valid user" }));
  });
  it("omits null and empty model names while preserving the valid option", async () => {
    api.models.mockResolvedValue({
      data: [
        { id: null, name: null },
        { id: "", name: "" },
        { id: 7, name: "Valid model" },
      ],
      total: 3,
    });
    render(<ModelAuditModelSelect tenantId={101} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("combobox", { name: "dsh.modelAuditView.filters.model_name" }));
    expect(await screen.findByRole("option", { name: "Valid model" })).toBeVisible();
    expect(api.models.mock.calls[0][0].tenant_id).toBe(101);
  });
});

// Coverage AC: AC-44, AC-45, AC-46, AC-49, AC-51.
describe("unassociated view uses its own filters and tenant/caller lifetime", () => {
  it("is lazy, hides unsupported filters and forwards existing root progress without extra row requests", async () => {
    render(<ModelAuditRequests tenantId={101} />);
    await screen.findByLabelText("dsh.contentSafety.readiness.all_hits: 2");
    expect(api.unassociated).not.toHaveBeenCalled();
    enterEvents();
    await screen.findByText(event.event_id);
    expect(screen.queryByRole("combobox", { name: "dsh.contentSafety.filters.state" })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "dsh.contentSafety.filters.direction" })).toBeNull();
    expect(api.groupRequests).not.toHaveBeenCalled();
    expect(api.body).not.toHaveBeenCalled();
    expect(api.unassociated).toHaveBeenCalledWith(
      {
        tenant_id: 101,
        association_status: "UNASSOCIATED",
        limit: 20,
        user_id: undefined,
        model_id: undefined,
        gateway_request_id: undefined,
        backend_request_id: undefined,
        start_at: undefined,
        end_at: undefined,
        cursor: undefined,
      },
      expect.any(AbortSignal),
    );
  });
  it("submits all six explicit conditions with uppercase UUIDs while preserving exact int64 metadata", async () => {
    render(<UnassociatedSafetyEvents tenantId={101} />);
    await screen.findByText(event.model_id);
    expect(screen.getByText(event.user_id)).toBeVisible();
    for (const [key, value] of [
      ["user", "11"],
      ["model", "7"],
      ["gateway", event.gateway_request_id],
      ["backend", "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB"],
      ["start", "2026-01-01T00:00"],
      ["end", "2026-01-08T00:00"],
    ] as const)
      change(key, value);
    search();
    await waitFor(() => expect(api.unassociated).toHaveBeenCalledTimes(2));
    expect(api.unassociated.mock.calls[1][0]).toMatchObject({
      tenant_id: 101,
      user_id: 11,
      model_id: 7,
      gateway_request_id: event.gateway_request_id,
      backend_request_id: "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB",
      start_at: new Date("2026-01-01T00:00").toISOString(),
      end_at: new Date("2026-01-08T00:00").toISOString(),
      cursor: undefined,
    });
  });
  it("marks only invalid IDs and both invalid time fields, blocking invalid transport", async () => {
    render(<UnassociatedSafetyEvents tenantId={101} />);
    await screen.findByText(event.event_id);
    change("user", "9007199254740993");
    expect(screen.getByLabelText(labels.user)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText(labels.model)).not.toHaveAttribute("aria-invalid", "true");
    expect(button("dsh.modelAuditView.search")).toBeDisabled();
    change("user", "11");
    change("gateway", "not-a-uuid");
    expect(screen.getByLabelText(labels.gateway)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText(labels.user)).not.toHaveAttribute("aria-invalid", "true");
    change("gateway", "");
    change("start", "2026-01-01T00:00");
    change("end", "2026-03-01T00:00");
    for (const key of ["start", "end"] as const)
      expect(screen.getByLabelText(labels[key])).toHaveAttribute("aria-invalid", "true");
    expect(api.unassociated).toHaveBeenCalledOnce();
  });
  it("clears event cursors on explicit filter change and refresh keeps the applied condition", async () => {
    api.unassociated.mockResolvedValue(page([event], "next"));
    render(<UnassociatedSafetyEvents tenantId={101} />);
    await screen.findByText(event.event_id);
    fireEvent.click(button("dsh.next"));
    await waitFor(() => expect(api.unassociated.mock.calls.at(-1)?.[0].cursor).toBe("next"));
    change("model", "7");
    search();
    await waitFor(() =>
      expect(api.unassociated.mock.calls.at(-1)?.[0]).toMatchObject({ model_id: 7, cursor: undefined }),
    );
    expect(button("dsh.previous")).toBeDisabled();
    change("model", "8");
    fireEvent.click(button("dsh.contentSafety.actions.refresh"));
    await waitFor(() => expect(api.unassociated).toHaveBeenCalledTimes(4));
    expect(api.unassociated.mock.calls[3][0]).toMatchObject({ model_id: 7, cursor: undefined });
    expect(screen.getByLabelText(labels.model)).toHaveValue("8");
  });
  it("retries the failed event cursor without dropping the active filter or leaking errors", async () => {
    api.unassociated
      .mockResolvedValueOnce(page([event], "next"))
      .mockRejectedValueOnce(Error("private query SQL"))
      .mockResolvedValue(page([]));
    render(<UnassociatedSafetyEvents tenantId={101} />);
    await screen.findByText(event.event_id);
    fireEvent.click(button("dsh.next"));
    await screen.findByRole("alert");
    expect(screen.queryByText("private query SQL")).toBeNull();
    expect(api.unassociated).toHaveBeenCalledTimes(2);
    fireEvent.click(button("dsh.contentSafety.actions.retry"));
    await screen.findByText("dsh.contentSafety.details.empty");
    expect(api.unassociated.mock.calls.slice(1).every((call) => call[0].cursor === "next")).toBe(true);
  });
  it("aborts tenant changes and ignores a late old-tenant event", async () => {
    let finish!: (value: ContentSafetyEventPage) => void;
    api.unassociated
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValue(page([{ ...event, event_id: "new-tenant" }]));
    const view = render(<UnassociatedSafetyEvents tenantId={101} />);
    await waitFor(() => expect(api.unassociated).toHaveBeenCalledOnce());
    const signal = api.unassociated.mock.calls[0][1] as AbortSignal;
    view.rerender(<UnassociatedSafetyEvents tenantId={202} />);
    await screen.findByText("new-tenant");
    expect(signal.aborted).toBe(true);
    await act(async () => finish(page([{ ...event, event_id: "old-private" }])));
    expect(screen.queryByText("old-private")).toBeNull();
  });
  it("clears hidden old-caller content on a same-tenant identity change", async () => {
    let finish!: (value: ContentSafetyEventPage) => void;
    api.unassociated.mockResolvedValueOnce(page([{ ...event, event_id: "old-visible" }])).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const context = (id: number): React.ContextType<typeof userContext> => ({
      user: { user_id: id, tenant_id: 101, role: "admin" },
      setUser: vi.fn(),
      savedComponents: [],
      checkComponentsName: vi.fn(),
      delComponent: vi.fn(),
      addSavedComponent: vi.fn().mockResolvedValue(null),
    });
    const view = render(
      <userContext.Provider value={context(11)}>
        <ModelAuditRequests tenantId={101} />
      </userContext.Provider>,
    );
    await screen.findByRole("button", { name: /Synthetic group/ });
    enterEvents();
    await screen.findByText("old-visible");
    fireEvent.click(button("dsh.contentSafety.actions.refresh"));
    await waitFor(() => expect(api.unassociated).toHaveBeenCalledTimes(2));
    const signal = api.unassociated.mock.calls[1][1] as AbortSignal;
    fireEvent.click(button("dsh.modelAuditView.return_results"));
    view.rerender(
      <userContext.Provider value={context(22)}>
        <ModelAuditRequests tenantId={101} />
      </userContext.Provider>,
    );
    await screen.findByRole("button", { name: /Synthetic group/ });
    expect(signal.aborted).toBe(true);
    await act(async () => finish(page([{ ...event, event_id: "previous-caller" }])));
    expect(screen.queryByText("previous-caller")).toBeNull();
    expect(screen.queryByText("old-visible")).toBeNull();
    expect(screen.queryByRole("button", { name: "dsh.modelAuditView.return_results" })).toBeNull();
  });
  it("does not refetch a hidden visited event page on focus, reconnect or returning", async () => {
    render(<ModelAuditRequests tenantId={101} />);
    await screen.findByRole("button", { name: /Synthetic group/ });
    enterEvents();
    await screen.findByText(event.event_id);
    fireEvent.click(button("dsh.modelAuditView.return_results"));
    fireEvent(window, new Event("focus"));
    fireEvent(window, new Event("online"));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30));
    });
    expect(api.unassociated).toHaveBeenCalledOnce();
    enterEvents();
    await screen.findByText(event.event_id);
    expect(api.unassociated).toHaveBeenCalledOnce();
  });
  it("keeps prior audit pagination and event drafts separate across view switches", async () => {
    api.page.mockResolvedValue({ items: [row], next_cursor: "audit-next", progress: ready });
    render(<ModelAuditRequests tenantId={101} initialView="requests" />);
    await screen.findByText(row.model_name);
    fireEvent.click(button("dsh.next"));
    await waitFor(() => expect(api.page.mock.calls.at(-1)?.[0].cursor).toBe("audit-next"));
    const count = api.page.mock.calls.length;
    enterEvents();
    await screen.findByText(event.event_id);
    change("user", "11");
    fireEvent.click(button("dsh.modelAuditView.return_results"));
    expect(screen.getByText(row.model_name)).toBeVisible();
    expect(button("dsh.previous")).toBeEnabled();
    expect(api.page).toHaveBeenCalledTimes(count);
    enterEvents();
    expect(screen.getByLabelText(labels.user)).toHaveValue("11");
    expect(api.unassociated).toHaveBeenCalledOnce();
  });
});
