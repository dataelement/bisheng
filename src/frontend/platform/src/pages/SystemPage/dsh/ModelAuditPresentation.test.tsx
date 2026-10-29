import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { AuditTreeNode, ModelAuditRecord } from "@/types/dshModelAudit";
import { ModelAuditGroup, ModelAuditSafetySummary } from "./ModelAuditGroup";
import { ModelAuditTree } from "./ModelAuditTree";
import { ModelAuditCard } from "./ModelAuditCard";

const timestamp = "2026-10-29T01:00:00Z";
// Coverage AC: AC-73.
it("hides the entire partial safety summary until both counters are ready", () => {
  const { container } = render(<ModelAuditSafetySummary
    progress={{ status_ready: true, name_ready: true, indexing_pending: false, safety_ready: true, safety_summary_as_of: timestamp }}
    own={{ label: "own_hits", ready: true, count: 2, hasHit: true }}
    branch={{ label: "branch_hits", ready: false, count: null }}
  />);
  expect(container).toBeEmptyDOMElement();
});

it("AC-73: keeps an unready conversation visible without pending statistics", () => {
  const summary = { ready: false, request_count: null, abnormal_count: null, known_abnormal: true, safety_ready: false, sensitive_hit_count: null, has_sensitive_hit: true };
  const node: AuditTreeNode = {
    conversation_key: "a".repeat(64), generation: "00000000-0000-4000-8000-000000000001",
    conversation_id: "Visible conversation", user_id: 1, user_name: "Synthetic user",
    parent_key: "", root_key: "a".repeat(64), relation_state: "MAIN", has_children: false, match_scope: "SELF",
    listed_at: timestamp, last_request_at: timestamp, updated_at: timestamp, request_count: 5, abnormal_count: 1,
    own_summary: summary, branch_summary: summary, summary_as_of: null,
  };
  render(<ModelAuditTree node={node} progress={{ status_ready: true, name_ready: true, indexing_pending: true, safety_ready: false }} query={{ limit: 20 }} expanded={false} onToggle={vi.fn()} onRefresh={vi.fn()} />);
  expect(screen.getByRole("button", { name: /Visible conversation/ })).toBeVisible();
  for (const key of ["summary_pending", "branch_pending", "known_abnormal", "own_count"])
    expect(screen.queryByText("dsh.modelAuditView.tree." + key)).toBeNull();
  expect(screen.queryByText("dsh.modelAuditView.summary.PREPARING")).toBeNull();
});

it("AC-75: leaves model and time in the header without request-kind or session-origin labels", () => {
  const row: ModelAuditRecord = {
    request_id: "synthetic-request", conversation_id: "synthetic-conversation", user_id: 1, user_name: "Synthetic user",
    model_id: 1, model_name: "Synthetic model", provider_name: "Synthetic provider", request_kind: "chat", session_origin: "main",
    context_invalid: false, association_status: "ASSOCIATED", effective_mode: "METADATA", started_at: timestamp, last_write_at: null,
    input_units: 1, input_bytes: 0, output_bytes: 0, model_result: "SUCCEEDED", response_result: "COMPLETED", usage_settlement: "SETTLED", content_status: "NOT_CAPTURED", usage: null, audit_status: "NORMAL",
  };
  render(<ModelAuditCard row={row} expanded={false} onToggle={vi.fn()} />);
  expect(screen.getByText("Synthetic model")).toBeVisible();
  expect(screen.getByRole("article").querySelector("header time")).toHaveAttribute("datetime", timestamp);
  expect(screen.queryByText("dsh.modelAuditView.kinds.chat")).toBeNull();
  expect(screen.queryByText("dsh.modelAuditView.sources.origin.main")).toBeNull();
});

// Coverage AC: AC-73.
it("keeps a flat conversation visible and restores counts only when indexing is ready", () => {
  const group = { conversation_key: "b".repeat(64), user_id: 1, conversation_id: "Flat conversation", listed_at: timestamp, last_request_at: timestamp, updated_at: timestamp, request_count: 4, abnormal_count: 0 };
  const props = { group, query: { limit: 20 }, expanded: false, onToggle: vi.fn() };
  const view = render(<ModelAuditGroup {...props} progress={{ status_ready: true, name_ready: true, indexing_pending: true }} />);
  expect(screen.getByRole("button", { name: /Flat conversation/ })).toBeVisible();
  expect(screen.queryByText("dsh.modelAuditView.group_count")).toBeNull();
  expect(screen.queryByText("dsh.modelAuditView.summary.NORMAL")).toBeNull();
  view.rerender(<ModelAuditGroup {...props} progress={{ status_ready: true, name_ready: true, indexing_pending: false }} />);
  expect(screen.getByText("dsh.modelAuditView.group_count")).toBeVisible();
  expect(screen.getByText("dsh.modelAuditView.summary.NORMAL")).toBeVisible();
});
