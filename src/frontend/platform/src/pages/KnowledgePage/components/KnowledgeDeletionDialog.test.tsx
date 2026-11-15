import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
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
    expect(screen.getByText(/Published assistant/)).toBeInTheDocument();
    expect(screen.queryByText("PRIVATE-SOURCE-ID")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText("deletion.slot_counts")).not.toBeInTheDocument();
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
