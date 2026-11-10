import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ModelAuditRecord } from "@/types/dshModelAudit";
import { dshTime } from "./common";

const bodies = vi.hoisted(() => ({ render: vi.fn() }));
vi.mock("./ModelAuditBody", () => ({
  ModelAuditBody: (props: { requestId: string }) => {
    bodies.render(props);
    return <section data-testid="body">Synthetic message content</section>;
  },
}));
vi.mock("./ModelAuditParent", () => ({
  ModelAuditParent: () => <span>Origin</span>,
}));
import { ModelAuditCard } from "./ModelAuditCard";

const row: ModelAuditRecord = {
  audit_status: "ABNORMAL",
  status_reasons: ["response_result:INTERRUPTED", "usage_settlement:UNCERTAIN"],
  status_pending: false,
  request_id: "synthetic-request",
  user_id: 20,
  user_name: "Audit Alice",
  model_id: 42,
  model_name: "Synthetic model",
  provider_name: "Synthetic provider",
  conversation_id: "synthetic-conversation",
  request_kind: "compaction",
  context_invalid: false,
  association_status: "ASSOCIATED",
  effective_mode: "CONTENT",
  started_at: "2026-10-16T10:00:00Z",
  last_write_at: null,
  input_units: 3,
  input_bytes: 100,
  output_bytes: 200,
  model_result: "SUCCEEDED",
  response_result: "INTERRUPTED",
  usage_settlement: "UNCERTAIN",
  content_status: "COMPLETE",
  usage: {
    input_tokens: 10,
    output_tokens: 20,
    total_tokens: 30,
    status: "SETTLED",
  },
};
beforeEach(() => vi.clearAllMocks());

it("uses localized unavailable text when the user no longer exists", () => {
  render(
    <ModelAuditCard
      row={{ ...row, user_name: null }}
      expanded={false}
      onToggle={vi.fn()}
    />,
  );
  expect(screen.getByText("dsh.modelAuditView.user_unavailable")).toBeVisible();
  expect(screen.queryByText(/#20/)).toBeNull();
});

it("AC-72: groups business request details under a heading without IDs or duplicate metadata", () => {
  render(
    <ModelAuditCard
      row={row}
      expanded={false}
      onToggle={vi.fn()}
    />,
  );
  const card = screen.getByRole("article");
  expect(card).toHaveClass("relative");
  expect(card.querySelector("dt.sr-only")).toBeTruthy();
  const header = card.querySelector("header")!;
  expect(header).toHaveClass("text-xs");
  expect(within(header).getByText(row.model_name)).toBeVisible();
  expect(within(header).getByText("Audit Alice")).toBeVisible();
  expect(header.textContent).not.toContain("#20");
  expect(screen.queryByText(row.request_id)).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "dsh.modelAuditView.request_details" }),
  );
  const details = screen.getByRole("region", { name: "dsh.modelAuditView.request_details" });
  expect(within(details).getByRole("heading", { name: "dsh.modelAuditView.request_details", level: 3 })).toBeVisible();
  expect(within(details).getAllByRole("term")).toHaveLength(5);
  for (const axis of ["model_result", "response_result", "usage_settlement", "content_status"])
    expect(within(details).getByText("dsh.modelAuditView.axes." + axis)).toBeVisible();
  expect(screen.queryByText(row.request_id)).toBeNull();
  expect(screen.queryByText(row.conversation_id!)).toBeNull();
  expect(screen.getAllByText(row.model_name)).toHaveLength(1);
  for (const label of ["dsh.contentSafety.details.source", "dsh.contentSafety.details.model_started_at", "dsh.modelAuditView.conversation", "dsh.modelAuditView.filters.request_id"])
    expect(within(details).queryByText(label)).toBeNull();
  expect(screen.getByRole("button", { name: "dsh.modelAuditView.request_details" })).toHaveAttribute("aria-controls", details.id);
  expect(bodies.render).not.toHaveBeenCalled();
});

it("places the original between the request header and the independently colored status footer", () => {
  const toggle = vi.fn();
  render(
    <ModelAuditCard
      row={row}
      tenantId={2}
      expanded
      onToggle={toggle}
    />,
  );
  const card = screen.getByRole("article");
  const body = screen.getByTestId("body");
  const footer = card.querySelector("footer")!;
  expect(
    body.compareDocumentPosition(footer) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    card.querySelector("header")!.compareDocumentPosition(body) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    within(footer).getByText("dsh.modelAuditView.summary.ABNORMAL"),
  ).toHaveClass("text-destructive");
  expect(
    within(footer).queryByText("dsh.modelAuditView.states.COMPLETE"),
  ).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "dsh.modelAuditView.request_details" }),
  );
  expect(
    screen.getByText("dsh.modelAuditView.states.INTERRUPTED"),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "dsh.modelAuditView.timeline" }),
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: "dsh.modelAuditView.sources.parent" }),
  ).toBeNull();
  fireEvent.keyDown(body, { key: "Escape" });
  expect(toggle).toHaveBeenCalledOnce();
  expect(
    screen.getByRole("button", { name: "dsh.modelAuditView.collapse" }),
  ).toHaveFocus();
});

it("does not make metadata-only or uncaptured records fetchable", () => {
  const onToggle = vi.fn();
  render(
    <ModelAuditCard
      row={{
        ...row,
        effective_mode: "METADATA",
        content_status: "NOT_CAPTURED",
      }}
      expanded={false}
      onToggle={onToggle}
    />,
  );
  const button = screen.getByRole("button", {
    name: "dsh.modelAuditView.original",
  });
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(onToggle).not.toHaveBeenCalled();
  expect(bodies.render).not.toHaveBeenCalled();
});

it("AC-12, AC-13: shows model and response reasons independently and handles old records", () => {
  const { rerender } = render(
    <ModelAuditCard
      row={{
        ...row,
        model_result: "FAILED",
        model_error_code: "upstream_http_401",
        response_result: "ERROR",
        response_error_code: "error_response",
      }}
      expanded={false}
      onToggle={vi.fn()}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "dsh.modelAuditView.request_details" }),
  );
  expect(screen.getByText("dsh.modelAuditView.failures.model")).toBeVisible();
  expect(
    screen.getByText(/dsh.modelAuditView.failures.authentication/),
  ).toBeVisible();
  expect(
    screen.getByText(/dsh.modelAuditView.failures.http_status/),
  ).toBeVisible();
  expect(
    screen.getByText("dsh.modelAuditView.failures.error_response"),
  ).toBeVisible();
  rerender(
    <ModelAuditCard
      row={row}
      expanded={false}
      onToggle={vi.fn()}
    />,
  );
  expect(screen.queryByText("dsh.modelAuditView.failures.model")).toBeNull();
  expect(
    screen.getByText("dsh.modelAuditView.failures.unavailable"),
  ).toBeVisible();
});

// Coverage AC: AC-72.
it("keeps the request time in the header without repeating model execution metadata", () => {
  const started = "2026-10-16T11:22:33Z";
  render(<ModelAuditCard row={{ ...row, record_origin: "MODEL", model_entered: true, model_started_at: started }} expanded={false} onToggle={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "dsh.modelAuditView.request_details" }));
  expect(screen.queryByText("dsh.contentSafety.details.model_started_at")).toBeNull();
  expect(screen.queryByText(dshTime(started))).toBeNull();
  expect(screen.getByRole("article").querySelector("header time")).toHaveAttribute("datetime", row.started_at);
});

it.each([
  { entered: null, expected: "UNOBSERVED" },
  { entered: false, expected: "NOT_ENTERED" },
  { entered: true, expected: "UNOBSERVED" },
] as const)("AC-72: shows one model result without inventing execution for entered=$entered", ({ entered, expected }) => {
  render(<ModelAuditCard row={{ ...row, record_origin: "EXTERNAL_SAFETY", model_entered: entered, model_result: null, response_result: null, usage_settlement: null, content_status: "NOT_CAPTURED" }} expanded={false} onToggle={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "dsh.modelAuditView.request_details" }));
  const details = screen.getByRole("region", { name: "dsh.modelAuditView.request_details" });
  expect(within(details).getAllByText("dsh.modelAuditView.axes.model_result")).toHaveLength(1);
  expect(within(details).getByText("dsh.contentSafety.model_entry." + expected)).toBeVisible();
  expect(within(details).getByText("dsh.modelAuditView.states.NOT_CAPTURED")).toBeVisible();
  expect(within(details).queryByText("dsh.modelAuditView.states.SUCCEEDED")).toBeNull();
  expect(within(details).getAllByRole("term")).toHaveLength(4);
  expect(within(details).getAllByText(entered === false ? "dsh.contentSafety.model_entry.NOT_APPLICABLE" : "dsh.modelAuditView.states.UNKNOWN")).toHaveLength(2);
  expect(bodies.render).not.toHaveBeenCalled();
});

it("AC-72: keeps sanitized failure reasons and the existing details toggle", () => {
  render(<ModelAuditCard row={{ ...row, model_result: "FAILED", model_error_code: "private upstream diagnostic", response_error_code: "peer_disconnected" }} expanded={false} onToggle={vi.fn()} />);
  const toggle = screen.getByRole("button", { name: "dsh.modelAuditView.request_details" });
  fireEvent.click(toggle);
  const details = screen.getByRole("region", { name: "dsh.modelAuditView.request_details" });
  expect(within(details).getByText("dsh.modelAuditView.failures.unavailable")).toBeVisible();
  expect(within(details).getByText("dsh.modelAuditView.failures.peer_disconnected")).toBeVisible();
  expect(within(details).queryByText("private upstream diagnostic")).toBeNull();
  fireEvent.click(toggle);
  expect(screen.queryByRole("region", { name: "dsh.modelAuditView.request_details" })).toBeNull();
  expect(toggle).toHaveAttribute("aria-expanded", "false");
});
