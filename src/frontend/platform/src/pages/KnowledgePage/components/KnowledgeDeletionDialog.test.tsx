import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KnowledgeDeletionDialog } from "./KnowledgeDeletionDialog";
import type { useKnowledgeDeletion, KnowledgeDeletionView } from "../hooks/useKnowledgeDeletion";
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
const page = {
  data: [
    {
      disclosure: {
        source: {
          tenant_id: 901,
          source_type: "assistant",
          source_id: "PRIVATE-SOURCE-ID",
          source_version: null,
        },
        name: "Published assistant",
        version_label: "v2",
        entry: null,
      },
      matched_slot_count: 3,
    },
  ],
  page_size: 50,
  has_more: false,
  next_cursor: null,
};
const base: KnowledgeDeletionView = {
  command: { spaceId: 3, kind: "files", items: [{ id: 7, type: "file" }] },
  readonly: false,
  busy: false,
  force: false,
  dispatched: false,
  result: {
    confirmation_id: "plan",
    plan_digest: "digest",
    expires_at: "2030-01-01",
    check_complete: true,
    can_execute: true,
    requires_skip_confirmation: true,
    valid_items: [{ id: 7, type: "file", name: "deletable.txt" }],
    invalid_items: [{ name: "used.txt", reason: "referenced" }],
    impact: {
      file_count: 1,
      source_counts: { assistant: 1 },
      restricted_counts: { workflow_version: 5 },
      source_page: page,
    },
  },
  page,
};
function operation(view: KnowledgeDeletionView): ReturnType<typeof useKnowledgeDeletion> {
  return {
    view,
    open: vi.fn(),
    confirm: vi.fn(),
    force: vi.fn(),
    status: vi.fn(),
    more: vi.fn(),
    refresh: vi.fn(),
    cancel: vi.fn(),
  };
}
describe("knowledge deletion consent", () => {
  it("shows disclosed names and restricted counts without source IDs or guessed links", () => {
    render(<KnowledgeDeletionDialog operation={operation(base)} />);
    const details = screen.getByRole("table", { name: "deletion.source_details" });
    const source = within(details).getByRole("row", { name: /Published assistant/ });
    expect(within(source).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
      "deletion.source_assistant", "v2", "3",
    ]);
    const invalid = screen.getByRole("table", { name: "deletion.invalid_items" });
    expect(within(invalid).getByRole("row", { name: "used.txt deletion.reason_referenced" })).toBeVisible();
    expect(screen.queryByText("PRIVATE-SOURCE-ID")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText("deletion.slot_counts")).not.toBeInTheDocument();
  });
  it("aligns reference counts in one row per type, including zero and slot-only counts", () => {
    render(<KnowledgeDeletionDialog operation={operation({
      ...base,
      command: { spaceId: 3, kind: "delete" },
      readonly: true,
      result: undefined,
      page: undefined,
      inspection: {
        check_complete: true,
        blocked: false,
        source_counts: { knowledge: 0, assistant: 4 },
        restricted_counts: { assistant: 2 },
        slot_counts: { assistant: 6, workflow_version: 5 },
        source_page: page,
      },
    })} />);
    const summary = screen.getByRole("table", { name: "deletion.references" });
    expect(within(summary).getByRole("columnheader", { name: "deletion.slot_counts" })).toBeVisible();
    expect(within(summary).getByRole("row", { name: "deletion.source_assistant 4 2 6" })).toBeVisible();
    expect(within(summary).getByRole("row", { name: "deletion.source_workflow_version 0 0 5" })).toBeVisible();
    expect(within(summary).getByRole("row", { name: "deletion.source_knowledge 0 0 0" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "deletion.close" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "deletion.review" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Close" })).toBeEnabled();
  });
  it("hides knowledge and default model counts only for space deletion", () => {
    const impact = { ...base.result!.impact, source_counts: { knowledge: 4, model_default: 3, assistant: 1 }, restricted_counts: { knowledge: 2, model_default: 1, workflow_version: 5 } };
    const view = { ...base, command: { spaceId: 3, kind: "delete" as const }, result: { ...base.result!, impact } };
    const { rerender } = render(<KnowledgeDeletionDialog operation={operation(view)} />);
    expect(screen.queryByText(/deletion.source_knowledge/)).not.toBeInTheDocument();
    expect(screen.queryByText(/deletion.source_model_default/)).not.toBeInTheDocument();
    expect(screen.getByRole("row", { name: "deletion.source_assistant 1 0" })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: "deletion.source_workflow_version 0 5" })).toBeInTheDocument();
    rerender(<KnowledgeDeletionDialog operation={operation({ ...view, command: base.command })} />);
    expect(screen.getByRole("row", { name: "deletion.source_knowledge 4 2" })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: "deletion.source_model_default 3 1" })).toBeInTheDocument();
  });
  it("requires explicit skip acknowledgement and retires it for a new plan", () => {
    const op = operation(base);
    const { rerender } = render(<KnowledgeDeletionDialog operation={op} />);
    expect(screen.getByRole("button", { name: "deletion.confirm" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "deletion.confirm" }));
    expect(op.confirm).toHaveBeenCalledWith(true, false);
    rerender(
      <KnowledgeDeletionDialog
        operation={operation({ ...base, result: { ...base.result!, plan_digest: "changed" } })}
      />,
    );
    expect(screen.getByRole("button", { name: "deletion.confirm" })).toBeDisabled();
  });
  it("never offers force for files or incomplete coverage", () => {
    const { rerender } = render(
      <KnowledgeDeletionDialog
        operation={operation({ ...base, result: { ...base.result!, can_execute: false } })}
      />,
    );
    expect(screen.queryByRole("button", { name: "deletion.force_review" })).not.toBeInTheDocument();
    rerender(
      <KnowledgeDeletionDialog
        operation={operation({
          ...base,
          command: { spaceId: 3, kind: "delete" },
          code: 10994,
          result: undefined,
        })}
      />,
    );
    expect(screen.queryByRole("button", { name: "deletion.force_review" })).not.toBeInTheDocument();
  });
  it("keeps pending cleanup visible and offers only same-operation retry and status", () => {
    render(
      <KnowledgeDeletionDialog
        operation={operation({
          ...base,
          dispatched: true,
          status: {
            job_id: "plan",
            state: "pending",
            business_phase: "finalized",
            completed_steps: ["fga"],
          },
        })}
      />,
    );
    expect(screen.getByRole("button", { name: "deletion.close" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "deletion.status" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "deletion.review" })).not.toBeInTheDocument();
    expect(screen.getByText("deletion.pending")).toBeInTheDocument();
  });
});

it("names an offline workflow and the setting that still references the space", () => {
  const workflowPage = {
    ...page,
    data: [{
      disclosure: {
        source: {
          tenant_id: 1,
          source_type: "workflow_version",
          source_id: "PRIVATE-FLOW",
          source_version: "4776",
        },
        name: "测试删除",
        version_label: "v0",
        entry: "/flow/PRIVATE-FLOW/",
      },
      matched_slot_count: 1,
      locations: ["workflow_knowledge_retriever"],
    }],
  };
  render(<KnowledgeDeletionDialog operation={operation({
    ...base,
    page: workflowPage,
    result: {
      ...base.result,
      impact: {
        ...base.result.impact,
        source_counts: { workflow_version: 1 },
        source_page: workflowPage,
      },
    },
  })} />);
  expect(screen.getByRole("link", { name: "测试删除" })).toHaveAttribute("href", "/flow/PRIVATE-FLOW/");
  expect(screen.getByText(/deletion\.workflow_unlink/)).toBeVisible();
  expect(screen.getByText(/deletion\.location_workflow_knowledge_retriever/)).toBeVisible();
  expect(screen.queryByText("PRIVATE-FLOW")).not.toBeInTheDocument();
  expect(screen.queryByText("4776")).not.toBeInTheDocument();
});

it("explains failed source tasks instead of displaying only a generic resource conflict", () => {
  const view = { ...base, result: undefined, code: 10999, reason: "source_space_move_input_required", error: "Generic resource conflict" };
  render(<KnowledgeDeletionDialog operation={operation(view)} />);
  expect(screen.getByRole("alert")).toHaveTextContent("deletion.source_tasks_block_delete");
  expect(screen.queryByText("Generic resource conflict")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "deletion.confirm" })).toBeDisabled();
});
