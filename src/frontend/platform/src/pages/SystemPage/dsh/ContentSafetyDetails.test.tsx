import * as React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import request from "@/controllers/request";
import { contentSafetyStates } from "@/types/dshContentSafety";
import type { ContentSafetyEventMetadata, ContentSafetyEventPage } from "@/types/dshContentSafety";
import type { ModelAuditQuery, ModelAuditRecord } from "@/types/dshModelAudit";
import { ContentSafetyDetails, ContentSafetyEventDetails } from "./ContentSafetyDetails";
import { ModelAuditCard } from "./ModelAuditCard";
import { ModelAuditFilters } from "./ModelAuditFilters";
import { ModelAuditModelSelect } from "./ModelAuditModelSelect";
import { ModelAuditRequests } from "./ModelAuditPanel";
import en from "../../../../public/locales/en-US/bs.json";
import zh from "../../../../public/locales/zh-Hans/bs.json";
import ja from "../../../../public/locales/ja/bs.json";

const api = vi.hoisted(() => ({
  events: vi.fn(),
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
function card(extra: Partial<ModelAuditRecord> = {}, expanded = false) {
  return render(
    <ModelAuditCard
      row={{ ...row, ...extra }}
      tenantId={101}
      expanded={expanded}
      onToggle={vi.fn()}
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
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
beforeEach(() => {
  vi.resetAllMocks();
  api.events.mockResolvedValue(page([], null, "UNREPORTED"));
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
  // Coverage AC: AC-68, AC-69.
  it("shows only escaped matched words and check time, without technical identifiers", () => {
    render(<ContentSafetyEventDetails event={{ ...event, matched_words: { input: [], output: ["<script>synthetic</script>"] } }} />);
    expect(screen.getByText("<script>synthetic</script>")).toBeVisible();
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText("dsh.contentSafety.details.occurred_at")).toBeVisible();
    expect(screen.getAllByRole("term")).toHaveLength(1);
    for (const key of ["source", "event_id", "event_kind", "event_version", "gateway_request_id", "backend_request_id", "policy_version", "builtin_digest", "hit_count", "request_started_at", "received_at", "drain_status", "rule_refs", "hit_count_truncated"])
      expect(screen.queryByText("dsh.contentSafety.details." + key)).toBeNull();
    for (const value of [event.event_id, event.gateway_request_id, event.source_id, event.builtin_digest, "dsh.contentSafety.drain.usage_hint"])
      expect(screen.queryByText(value)).toBeNull();
  });
  it("hides details and never loads events when all checks passed", () => {
    card({ content_safety_state: "PASSED", stage_results: { input: "PASSED", output: "PASSED" }, has_sensitive_hit: false });
    expect(screen.queryByRole("button", { name: "dsh.contentSafety.actions.view_details" })).toBeNull();
    expect(api.events).not.toHaveBeenCalled();
    expect(screen.getAllByText(/states.PASSED/)).toHaveLength(3);
  });
  it.each([
    { has_sensitive_hit: true },
    { input_sensitive_hit: true },
    { output_sensitive_hit: true },
  ])("retains details for historical hit facts even if the latest stages passed: %j", async (hit) => {
    api.events.mockResolvedValue(page());
    card({ content_safety_state: "PASSED", stage_results: { input: "PASSED", output: "PASSED" }, ...hit });
    fireEvent.click(button("dsh.contentSafety.actions.view_details"));
    await waitFor(() => expect(api.events).toHaveBeenCalledTimes(1));
  });
  it("aborts opened details when an updated row reports all checks passed", async () => {
    api.events.mockImplementation(() => new Promise(() => {}));
    const view = card({ content_safety_state: "UNREPORTED" });
    fireEvent.click(button("dsh.contentSafety.actions.view_details"));
    await waitFor(() => expect(api.events).toHaveBeenCalledTimes(1));
    const signal = api.events.mock.calls[0][2] as AbortSignal;
    view.rerender(<ModelAuditCard row={{ ...row, content_safety_state: "PASSED", stage_results: { input: "PASSED", output: "PASSED" }, has_sensitive_hit: false }} tenantId={101} expanded={false} onToggle={vi.fn()} />);
    expect(signal.aborted).toBe(true);
    expect(screen.queryByRole("button", { name: "dsh.contentSafety.actions.view_details" })).toBeNull();
    expect(screen.queryByLabelText("dsh.contentSafety.details.title")).toBeNull();
  });
  it("retains earlier events after next-page failure and retries exactly that cursor", async () => {
    api.events
      .mockResolvedValueOnce(page([{ ...event, matched_words: { input: [], output: ["initial-word"] } }], "page2"))
      .mockRejectedValueOnce(Error("synthetic private SQL"))
      .mockResolvedValueOnce(page([{ ...event, event_id: "second", matched_words: { input: [], output: ["second-word"] } }]));
    render(<ContentSafetyDetails requestId={row.request_id} tenantId={101} />);
    fireEvent.click(await screen.findByRole("button", { name: "dsh.contentSafety.actions.load_more" }));
    await screen.findByRole("alert");
    expect(screen.getByText("initial-word")).toBeVisible();
    expect(screen.queryByText("synthetic private SQL")).toBeNull();
    fireEvent.click(button("dsh.contentSafety.actions.retry"));
    await screen.findByText("second-word");
    expect(api.events.mock.calls.slice(1).every((call) => call[1].cursor === "page2")).toBe(true);
    expect(screen.getByText("initial-word")).toBeVisible();
  });
  it("retries failed refresh from the first page, not the stale next cursor", async () => {
    api.events
      .mockResolvedValueOnce(page([{ ...event, matched_words: { input: [], output: ["initial-word"] } }], "stale-next"))
      .mockRejectedValueOnce(Error("offline"))
      .mockResolvedValueOnce(page([{ ...event, event_id: "fresh", matched_words: { input: [], output: ["fresh-word"] } }], "new-next"));
    render(<ContentSafetyDetails requestId={row.request_id} tenantId={101} />);
    await screen.findByText("initial-word");
    fireEvent.click(button("dsh.contentSafety.actions.refresh"));
    await screen.findByRole("alert");
    fireEvent.click(button("dsh.contentSafety.actions.retry"));
    await screen.findByText("fresh-word");
    expect(api.events).toHaveBeenLastCalledWith(
      row.request_id,
      { tenant_id: 101, cursor: undefined, limit: 20 },
      expect.any(AbortSignal),
    );
    expect(screen.queryByText("initial-word")).toBeNull();
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
    await act(async () => finish(page([{ ...event, matched_words: { input: [], output: ["initial-word"] } }])));
    expect(screen.queryByText("initial-word")).toBeNull();
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

// Coverage AC: AC-64.
describe("audit views without detached safety checks", () => {
  it.each(["groups", "unassociated"] as const)(
    "keeps %s available without an unlinked-check entry or query",
    async (initialView) => {
      const transport = vi.spyOn(request, "get").mockRejectedValue(new Error("Unexpected query"));
      render(<ModelAuditRequests tenantId={101} initialView={initialView} />);
      await waitFor(() => expect(initialView === "groups" ? api.groups : api.page).toHaveBeenCalled());
      expect(screen.queryByRole("button", {
        name: "dsh.contentSafety.association.unassociated_title",
      })).toBeNull();
      expect(screen.queryByLabelText("dsh.contentSafety.association.unassociated_title")).toBeNull();
      expect(screen.queryByRole("button", { name: "dsh.modelAuditView.views.requests" })).toBeNull();
      expect(screen.queryByRole("button", { name: "dsh.modelAuditView.return_results" })).toBeNull();
      for (const view of ["groups", "unassociated"])
        expect(screen.getByRole("button", { name: "dsh.modelAuditView.views." + view })).toBeVisible();
      if (initialView === "unassociated")
        expect(api.page).toHaveBeenCalledWith(
          expect.objectContaining({ tenant_id: 101, association_status: "UNASSOCIATED" }),
          expect.any(AbortSignal),
        );
      fireEvent.click(button("dsh.modelAuditView.refresh_records"));
      fireEvent(window, new Event("focus"));
      fireEvent(window, new Event("online"));
      await waitFor(() => expect(initialView === "groups" ? api.groups : api.page).toHaveBeenCalledTimes(2));
      expect(transport.mock.calls.some(([url]) => url === "/api/v1/dsh/admin/model-audit/content-safety-events")).toBe(false);
    },
  );
});

// Coverage AC: AC-66.
describe("matched rule words in authorized check details", () => {
  it.each(["input", "output"] as const)("renders %s matched words as text without injecting markup", (direction) => {
    const word = "<img src=x onerror=synthetic>";
    const words = { input: direction === "input" ? [word] : [], output: direction === "output" ? [word] : [] };
    const stages = direction === "input" ? { input: "BLOCKED" as const, output: "NOT_APPLICABLE" as const } : event.stage_results;
    render(<ContentSafetyEventDetails event={{ ...event, stage_results: stages, matched_words: words }} />);
    expect(screen.getByText(word)).toBeVisible();
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByLabelText("dsh.contentSafety.details.matched_words")).toBeVisible();
  });
  it("shows unknown instead of reconstructing words for legacy blocked events", () => {
    render(<ContentSafetyEventDetails event={event} />);
    expect(screen.getByText("dsh.contentSafety.details.matched_words_unavailable")).toBeVisible();
  });
  it("validates and retains a captured word snapshot in the actual API wrapper", async () => {
    const actual = await vi.importActual<typeof import("@/controllers/API/dshContentSafety")>("@/controllers/API/dshContentSafety");
    const words = { input: [], output: ["synthetic-frozen"] };
    vi.spyOn(request, "get").mockResolvedValue(page([{ ...event, rule_refs: ["custom:101:4:0"], matched_words: words } as unknown as ContentSafetyEventMetadata]));
    expect((await actual.getAuditSafetyEvents("request-1", { limit: 20 })).items[0].matched_words).toEqual(words);
  });
  it.each([undefined, null])("accepts legacy word availability %j without guessing", async (words) => {
    const actual = await vi.importActual<typeof import("@/controllers/API/dshContentSafety")>("@/controllers/API/dshContentSafety");
    const legacy = { ...event, rule_refs: ["custom:101:4:0"] };
    if (words === null) Object.assign(legacy, { matched_words: null });
    vi.spyOn(request, "get").mockResolvedValue(page([legacy]));
    expect((await actual.getAuditSafetyEvents("request-1", { limit: 20 })).items[0].matched_words).toBe(words);
  });
  it.each([
    { input: [], output: [123] }, { input: [], output: ["x".repeat(257)] },
    { input: ["wrong-stage"], output: [] }, { input: [], output: Array.from({length: 21}, (_, i) => String(i)) },
    { input: [], output: ["same", "same"] }, { input: [], output: [String.fromCharCode(0xd800)] },
  ])("rejects malformed word snapshots without exposing them: %j", async (words) => {
    const actual = await vi.importActual<typeof import("@/controllers/API/dshContentSafety")>("@/controllers/API/dshContentSafety");
    vi.spyOn(request, "get").mockResolvedValue(page([{ ...event, rule_refs: ["custom:101:4:0"], matched_words: words } as unknown as ContentSafetyEventMetadata]));
    await expect(actual.getAuditSafetyEvents("request-1", { limit: 20 })).rejects.toThrow("Invalid DSH content safety response");
  });
});
