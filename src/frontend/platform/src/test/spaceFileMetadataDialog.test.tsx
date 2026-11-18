import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ApiError } from "@bisheng/api-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpaceFileMetadataDialog } from "@/pages/KnowledgePage/components/SpaceFileMetadataDialog";
import { knowledgeSpaceApi, type JobState } from "@/controllers/API/knowledgeSpace";
import type { FileMetadata } from "@/controllers/API/knowledgeIndex";

const mocks = vi.hoisted(() => ({ read: vi.fn(), save: vi.fn(), error: vi.fn() }));
vi.mock("@/controllers/API/knowledgeProcessing", () => ({ readMetadataSchema: mocks.read }));
vi.mock("@/controllers/API/knowledgeIndex", () => ({ updateFileMetadata: mocks.save }));
vi.mock("@/controllers/request", () => ({ default: {}, showApiError: mocks.error }));
vi.mock("@/components/bs-ui/calendar/datePicker", () => ({
  DatePicker: ({ value, onChange, placeholder }: { value?: Date; onChange: (date: Date) => void; placeholder: string }) =>
    <input aria-label={placeholder} value={value?.toISOString() ?? ""} onChange={event => onChange(new Date(event.target.value))} />,
}));
vi.mock("@/pages/KnowledgePage/components/SpaceProcessingProgress", () => ({
  SpaceProcessingProgress: ({ onStateChange, onCompleted }: { onStateChange: (state: JobState) => void; onCompleted: () => void }) => <>
    <button onClick={() => { onStateChange("succeeded"); onCompleted(); }}>complete-job</button>
    <button onClick={() => onStateChange("failed")}>fail-job</button>
  </>,
}));
const scope = { identityKey: "user:7", tenantId: 60, managementTenantId: 60, view: "ordinary" as const };
const clients: QueryClient[] = [];
const plan = { confirmation_id: "plan", plan_digest: "digest", can_execute: true, check_complete: true, valid_items: [], invalid_items: [], expires_at: "later", impact: {}, requires_skip_confirmation: false };
const fields = [
  { field_name: "title", field_type: "string" }, { field_name: "count", field_type: "number" }, { field_name: "date", field_type: "time" },
];
function mount(info: FileMetadata = { user_metadata: {} }, onSaved = vi.fn().mockResolvedValue(undefined)) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } }, logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() } });
  clients.push(client);
  const close = vi.fn();
  const draw = (fileId = 89, currentScope = scope, spaceId = 7) => <QueryClientProvider client={client}><SpaceFileMetadataDialog scope={currentScope} spaceId={spaceId} fileId={fileId} info={info} onClose={close} onSaved={onSaved} /></QueryClientProvider>;
  return { ...render(draw()), draw, close, onSaved };
}
async function openCreate() {
  fireEvent.click(await screen.findByRole("button", { name: "metadatainfor.addMetadata" }));
  fireEvent.click(screen.getByRole("button", { name: "metadatainfor.createMetadata" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "fileMetadata.confirmCreate" })).toBeEnabled());
}
beforeEach(() => {
  vi.restoreAllMocks(); vi.clearAllMocks();
  mocks.read.mockResolvedValue({ revision: 3, fields });
  mocks.save.mockResolvedValue({});
  vi.spyOn(knowledgeSpaceApi, "listProcessingJobs").mockResolvedValue({ data: [], total: 0 });
});
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); });

it("adds existing fields, edits all three types and replaces only this file's values", async () => {
  mount({ user_metadata: { title: { field_type: "string", field_value: "old" }, date: { field_type: "time", field_value: "1700000000" } } });
  fireEvent.click(await screen.findByRole("button", { name: "metadatainfor.addMetadata" }));
  expect(screen.queryByRole("button", { name: "title" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "count" }));
  fireEvent.change(screen.getByLabelText("title"), { target: { value: "new" } });
  fireEvent.change(screen.getByLabelText("count"), { target: { value: "12.5" } });
  fireEvent.change(screen.getByRole("textbox", { name: "date" }), { target: { value: "2026-01-01T12:00:00.000Z" } });
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(mocks.save).toHaveBeenCalledWith(89, { title: "new", count: "12.5", date: "1767268800" }));
});
it("keeps failed save drafts and removes only the file value", async () => {
  mocks.save.mockRejectedValueOnce(new Error("save failed"));
  mount({ user_metadata: { title: { field_value: "draft" }, count: { field_type: "number", field_value: "2" } } });
  await waitFor(() => expect(screen.getByRole("button", { name: "save" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "delete count" }));
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(mocks.error).toHaveBeenCalled());
  expect(screen.getByLabelText("title")).toHaveValue("draft");
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(mocks.save).toHaveBeenLastCalledWith(89, { title: "draft" }));
});
it("creates a space field through precheck and confirmation, attaching only after job success", async () => {
  const precheck = vi.spyOn(knowledgeSpaceApi, "precheckProcessing").mockResolvedValue(plan);
  const create = vi.spyOn(knowledgeSpaceApi, "createProcessingJob").mockResolvedValue({ job_id: "job", accepted: true, state: "accepted", reused: false });
  mount(); await openCreate();
  fireEvent.change(screen.getByLabelText("name"), { target: { value: "category" } });
  fireEvent.click(screen.getByRole("button", { name: "fileMetadata.confirmCreate" }));
  await screen.findByText("fileMetadata.schemaPending");
  expect(precheck).toHaveBeenCalledWith(7, expect.objectContaining({ kind: "metadata_schema_change", parameters: { expected_schema_revision: 3, changes: [{ operation: "add", field_name: "category", field_type: "string" }] } }));
  expect(create).toHaveBeenCalled();
  expect(screen.queryByLabelText("category")).toBeNull();
  mocks.read.mockResolvedValue({ revision: 4, fields: [...fields, { field_name: "category", field_type: "string" }] });
  fireEvent.click(screen.getByText("complete-job"));
  await screen.findByLabelText("category");
  expect(mocks.save).not.toHaveBeenCalled();
});
it("rejects duplicate field names without dispatch and preserves the draft after async failure", async () => {
  const precheck = vi.spyOn(knowledgeSpaceApi, "precheckProcessing").mockResolvedValue(plan);
  vi.spyOn(knowledgeSpaceApi, "createProcessingJob").mockResolvedValue({ job_id: "job", accepted: true, state: "accepted", reused: false });
  mount(); await openCreate();
  fireEvent.change(screen.getByLabelText("name"), { target: { value: "title" } });
  fireEvent.click(screen.getByText("fileMetadata.confirmCreate"));
  expect(screen.getByRole("alert")).toHaveTextContent("nameExists");
  expect(precheck).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("name"), { target: { value: "category" } });
  fireEvent.click(screen.getByText("fileMetadata.confirmCreate"));
  fireEvent.click(await screen.findByText("fail-job"));
  expect(screen.getByLabelText("name")).toHaveValue("category");
  expect(screen.queryByLabelText("category")).toBeNull();
});
it("retries an uncertain dispatch with the same idempotency key and immutable draft", async () => {
  vi.spyOn(knowledgeSpaceApi, "precheckProcessing").mockResolvedValue(plan);
  const create = vi.spyOn(knowledgeSpaceApi, "createProcessingJob").mockRejectedValueOnce(new Error("network"))
    .mockResolvedValue({ job_id: "job", accepted: true, state: "accepted", reused: false });
  mount(); await openCreate();
  fireEvent.change(screen.getByLabelText("name"), { target: { value: "category" } });
  fireEvent.click(screen.getByText("fileMetadata.confirmCreate"));
  await screen.findByText("fileMetadata.uncertain");
  expect(screen.getByLabelText("name")).toBeDisabled();
  fireEvent.click(screen.getByText("fileMetadata.confirmCreate"));
  await screen.findByText("fileMetadata.schemaPending");
  expect(create.mock.calls[0][1]).toEqual(create.mock.calls[1][1]);
});
it.each(["file", "tenant"])("retires late save responses after a %s change", async kind => {
  let resolve!: () => void;
  mocks.save.mockImplementation(() => new Promise<void>(done => { resolve = done; }));
  const mounted = mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "save" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  mounted.rerender(kind === "file" ? mounted.draw(90) : mounted.draw(89, { ...scope, managementTenantId: 61 }));
  await act(async () => resolve());
  expect(mounted.close).not.toHaveBeenCalled(); expect(mounted.onSaved).not.toHaveBeenCalled();
});

it("keeps a rejected create draft editable without treating a business rejection as an unknown result", async () => {
  vi.spyOn(knowledgeSpaceApi, "precheckProcessing").mockResolvedValue(plan);
  const create = vi.spyOn(knowledgeSpaceApi, "createProcessingJob").mockRejectedValueOnce(
    new ApiError({ status_code: 18001, status_message: "rejected" }, { message: "rejected" }),
  );
  mount(); await openCreate();
  fireEvent.change(screen.getByLabelText("name"), { target: { value: "category" } });
  fireEvent.click(screen.getByText("fileMetadata.confirmCreate"));
  await waitFor(() => expect(mocks.error).toHaveBeenCalled());
  expect(create).toHaveBeenCalledOnce();
  expect(screen.getByLabelText("name")).toHaveValue("category");
  expect(screen.getByLabelText("name")).toBeEnabled();
  expect(screen.queryByText("fileMetadata.uncertain")).toBeNull();
});

it.each(["file", "space", "tenant"])("does not confirm a retired field precheck after a %s change", async kind => {
  let resolve!: (value: typeof plan) => void;
  const precheck = vi.spyOn(knowledgeSpaceApi, "precheckProcessing").mockImplementation(() => new Promise(done => { resolve = done; }));
  const create = vi.spyOn(knowledgeSpaceApi, "createProcessingJob");
  const mounted = mount(); await openCreate();
  fireEvent.change(screen.getByLabelText("name"), { target: { value: "category" } });
  fireEvent.click(screen.getByText("fileMetadata.confirmCreate"));
  await waitFor(() => expect(precheck).toHaveBeenCalledOnce());
  mounted.rerender(kind === "file" ? mounted.draw(90) : kind === "space" ? mounted.draw(89, scope, 8) : mounted.draw(89, { ...scope, managementTenantId: 61 }));
  await act(async () => resolve(plan));
  expect(create).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("category")).toBeNull();
  expect(mounted.onSaved).not.toHaveBeenCalled();
});
