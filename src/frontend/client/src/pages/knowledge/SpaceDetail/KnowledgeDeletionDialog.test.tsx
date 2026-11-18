import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { KnowledgeDeletionDialog } from "./KnowledgeDeletionDialog";
import { useKnowledgeDeletion } from "../hooks/useKnowledgeDeletion";
import * as api from "~/api/knowledgeDeletion";

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
  useAuthContext: () => ({ user: { id: "7", role: "USER" } }),
}));
jest.mock("~/api/knowledgeDeletion", () => ({
  readDeletionTenant: jest.fn(), precheckDeletion: jest.fn(), confirmDeletion: jest.fn(),
  getDeletionStatus: jest.fn(), inspectReferences: jest.fn(), pageReferences: jest.fn(),
}));
jest.mock("~/components/ui", () => {
  const Box = ({ children }: { children: ReactNode }) => <div>{children}</div>;
  return { Dialog: Box, DialogContent: Box, DialogHeader: Box, DialogTitle: Box, DialogFooter: Box };
});
jest.mock("@bisheng/ui", () => ({
  Button: ({ children, onClick, disabled }: { children: ReactNode; onClick: () => void; disabled?: boolean }) => <button onClick={onClick} disabled={disabled}>{children}</button>,
  Checkbox: () => null,
}));
const page: api.ReferencePage = { data: [], page_size: 50, has_more: false, next_cursor: null };
const plan = (): api.DeletePrecheck => ({
  confirmation_id: "plan-1", plan_digest: "digest", expires_at: "2030-01-01T00:00:00Z",
  check_complete: true, can_execute: true, valid_items: [], invalid_items: [], requires_skip_confirmation: false,
  impact: { source_counts: {}, restricted_counts: {}, source_page: page, file_count: 1 },
});
const commands: api.DeleteCommand[] = [
  { spaceId: 3, kind: "delete" },
  { spaceId: 3, kind: "files", items: [{ id: 4, type: "folder" }] },
  { spaceId: 3, kind: "files", items: [{ id: 5, type: "file" }] },
];
function Harness({ command, readonly = false }: { command: api.DeleteCommand; readonly?: boolean }) {
  const operation = useKnowledgeDeletion("current-scope");
  return (
    <>
      <button onClick={() => { void operation.open(command, readonly); }}>Open check</button>
      <KnowledgeDeletionDialog operation={operation} />
    </>
  );
}
beforeEach(() => {
  jest.mocked(api.readDeletionTenant).mockResolvedValue({ tenant: "2" });
  jest.mocked(api.precheckDeletion).mockResolvedValue(plan());
  jest.mocked(api.confirmDeletion).mockResolvedValue({ job_id: "plan-1", state: "succeeded" });
});

it.each(commands)("checks deletion on demand and hides references when none exist: %j", async (command) => {
  render(<Harness command={command} />);
  expect(api.readDeletionTenant).not.toHaveBeenCalled();
  expect(api.precheckDeletion).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Open check"));
  await screen.findByText("com_knowledge.deletion.irreversible");
  expect(api.precheckDeletion).toHaveBeenCalledWith(command, false, "2");
  expect(screen.queryByText("com_knowledge.deletion.source_counts")).toBeNull();
  expect(screen.queryByText("com_knowledge.deletion.restricted")).toBeNull();
  await act(async () => { fireEvent.click(screen.getByText("com_knowledge.deletion.confirm")); });
  expect(api.confirmDeletion).toHaveBeenCalledWith(3, {
    confirmation_id: "plan-1", plan_digest: "digest", idempotency_key: "delete:plan-1",
  }, "2");
});

it.each(commands)("shows existing dependencies inside the deletion flow and blocks normal deletion: %j", async (command) => {
  const referenced = plan();
  referenced.can_execute = false;
  referenced.impact.source_counts = { assistant: 1 };
  referenced.impact.source_page = { ...page, data: [{ disclosure: {
    source: { tenant_id: 2, source_type: "assistant", source_id: "private-id", source_version: null },
    name: "Policy assistant", version_label: null, entry: "/build/assistants/1",
  }, matched_slot_count: 1 }] };
  jest.mocked(api.precheckDeletion).mockResolvedValue(referenced);
  render(<Harness command={command} />);
  fireEvent.click(screen.getByText("Open check"));
  const details = within(await screen.findByRole("table", { name: "com_knowledge.deletion.source_details" }));
  expect(details.getByRole("link", { name: "Policy assistant" })).toHaveAttribute("href", "/build/assistants/1");
  expect(details.getByRole("cell", { name: "1" })).toBeVisible();
  expect(screen.getByText("com_knowledge.deletion.source_counts")).toBeVisible();
  expect(screen.getByText("com_knowledge.deletion.confirm")).toBeDisabled();
  expect(document.body.textContent).not.toContain("private-id");
  expect(api.confirmDeletion).not.toHaveBeenCalled();
});

it("hides knowledge and default model rows in the space deletion summary", async () => {
  const result = plan();
  result.impact.source_counts = { knowledge: 4, model_default: 3, assistant: 1 };
  result.impact.restricted_counts = { knowledge: 2, model_default: 1, workflow_version: 5 };
  jest.mocked(api.precheckDeletion).mockResolvedValue(result);
  render(<Harness command={commands[0]} />);
  fireEvent.click(screen.getByText("Open check"));
  const summary = within(await screen.findByRole("table", { name: "com_knowledge.deletion.references" }));
  const assistant = within(summary.getByRole("row", { name: /deletion.source_assistant/ }));
  const workflow = within(summary.getByRole("row", { name: /deletion.source_workflow_version/ }));
  expect(assistant.getByRole("cell", { name: "1" })).toBeVisible();
  expect(workflow.getByRole("cell", { name: "5" })).toBeVisible();
  expect(summary.queryByRole("rowheader", { name: "com_knowledge.deletion.source_knowledge" })).toBeNull();
  expect(summary.queryByRole("rowheader", { name: "com_knowledge.deletion.source_model_default" })).toBeNull();
  expect(summary.queryByRole("columnheader", { name: "com_knowledge.deletion.slot_counts" })).toBeNull();
});

it("shows zero counts and types present only in reference slots in the read-only table", async () => {
  jest.mocked(api.inspectReferences).mockResolvedValue({
    check_complete: true,
    blocked: false,
    source_counts: { assistant: 0 },
    restricted_counts: {},
    slot_counts: { workflow_version: 3 },
    source_page: page,
  });
  render(<Harness command={commands[0]} readonly />);
  fireEvent.click(screen.getByText("Open check"));
  const summary = within(await screen.findByRole("table", { name: "com_knowledge.deletion.references" }));
  expect(summary.getByRole("columnheader", { name: "com_knowledge.deletion.slot_counts" })).toBeVisible();
  const assistant = within(summary.getByRole("row", { name: /deletion.source_assistant/ }));
  const workflow = within(summary.getByRole("row", { name: /deletion.source_workflow_version/ }));
  expect(assistant.getAllByRole("cell")[0]).toHaveTextContent("0");
  expect(workflow.getByRole("cell", { name: "3" })).toBeVisible();
  expect(screen.queryByText("com_knowledge.deletion.confirm")).toBeNull();
  expect(screen.queryByRole("button", { name: "com_knowledge.deletion.close" })).toBeNull();
  expect(screen.getByRole("button", { name: "com_knowledge.deletion.review" })).toBeEnabled();
});

it("shows restricted counts without inventing a source name, and keeps incomplete checks blocked", async () => {
  const restricted = plan();
  restricted.can_execute = false;
  restricted.impact.restricted_counts = { workflow_version: 2 };
  jest.mocked(api.precheckDeletion).mockResolvedValueOnce(restricted).mockResolvedValueOnce({ ...plan(), check_complete: false });
  render(<Harness command={commands[0]} />);
  fireEvent.click(screen.getByText("Open check"));
  expect(await screen.findByText("com_knowledge.deletion.restricted")).toBeVisible();
  expect(screen.queryByRole("link")).toBeNull();
  fireEvent.click(screen.getByText("com_knowledge.deletion.close"));
  fireEvent.click(screen.getByText("Open check"));
  await waitFor(() => expect(screen.getByText("com_knowledge.deletion.confirm")).toBeDisabled());
  expect(await screen.findByText("com_knowledge.deletion.unavailable")).toBeVisible();
  expect(screen.queryByText("com_knowledge.deletion.source_counts")).toBeNull();
});
