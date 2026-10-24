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
      onNavigate={vi.fn()}
    />,
  );
  expect(screen.getByText("dsh.modelAuditView.user_unavailable")).toBeVisible();
  expect(screen.queryByText(/#20/)).toBeNull();
});

it("keeps request information compact, revealing exact IDs without fetching an original", () => {
  render(
    <ModelAuditCard
      row={row}
      expanded={false}
      onToggle={vi.fn()}
      onNavigate={vi.fn()}
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
  expect(screen.getByText(row.request_id)).toBeVisible();
  expect(screen.getByText(row.conversation_id!)).toBeVisible();
  expect(bodies.render).not.toHaveBeenCalled();
});

it("places the original between the request header and the independently colored status footer", () => {
  const navigate = vi.fn();
  const toggle = vi.fn();
  render(
    <ModelAuditCard
      row={row}
      tenantId={2}
      expanded
      onToggle={toggle}
      onNavigate={navigate}
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
  expect(navigate).not.toHaveBeenCalled();
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
      onNavigate={vi.fn()}
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
      onNavigate={vi.fn()}
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
      onNavigate={vi.fn()}
    />,
  );
  expect(screen.queryByText("dsh.modelAuditView.failures.model")).toBeNull();
  expect(
    screen.getByText("dsh.modelAuditView.failures.unavailable"),
  ).toBeVisible();
});

it("keeps the request start stable while separately showing actual model execution start", () => {
  const started = "2026-10-16T11:22:33Z";
  render(<ModelAuditCard row={{ ...row, record_origin: "MODEL", model_entered: true, model_started_at: started }} expanded={false} onToggle={vi.fn()} onNavigate={vi.fn()} />);
  expect(screen.getByRole("article").querySelector("header time")).toHaveTextContent(dshTime(row.started_at));
  fireEvent.click(screen.getByRole("button", { name: "dsh.modelAuditView.request_details" }));
  const label = screen.getByText("dsh.contentSafety.details.model_started_at");
  expect(label.nextElementSibling).toHaveTextContent(dshTime(started));
  expect(screen.getByRole("article").querySelector("header time")).toHaveAttribute("datetime", row.started_at);
});

it.each([
  { origin: "MODEL" as const, entered: undefined, expected: "dsh.contentSafety.details.unknown" },
  { origin: "MODEL" as const, entered: true, expected: "dsh.contentSafety.details.unknown" },
  { origin: "EXTERNAL_SAFETY" as const, entered: null, expected: "dsh.contentSafety.details.unknown" },
  { origin: "EXTERNAL_SAFETY" as const, entered: false, expected: "dsh.contentSafety.model_entry.NOT_APPLICABLE" },
])("shows an explicit model start state for $origin/$entered", ({ origin, entered, expected }) => {
  render(<ModelAuditCard row={{ ...row, record_origin: origin, model_entered: entered, model_started_at: null }} expanded={false} onToggle={vi.fn()} onNavigate={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "dsh.modelAuditView.request_details" }));
  const label = screen.getByText("dsh.contentSafety.details.model_started_at");
  expect(label.nextElementSibling).toHaveTextContent(expected);
  expect(screen.getByRole("article").querySelector("header time")).toHaveAttribute("datetime", row.started_at);
});
