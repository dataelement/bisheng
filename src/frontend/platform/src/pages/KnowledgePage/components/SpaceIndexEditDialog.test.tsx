import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpaceIndexEditDialog } from "./SpaceIndexEditDialog";

const mocks = vi.hoisted(() => ({
  space: { data: { metadata_fields: [] as { field_name: string }[] }, isSuccess: true, isInitialLoading: false, error: null },
  target: vi.fn(), chunks: vi.fn(), metadata: vi.fn(), save: vi.fn(),
}));
vi.mock("@/controllers/hooks/knowledge", () => ({
  knowledgeQueryKeys: { space: () => ["space", 7] },
  useKnowledgeSpaceInfo: () => mocks.space,
}));
vi.mock("@/controllers/API/knowledgeProcessing", () => ({ readProcessingTarget: mocks.target }));
vi.mock("@/controllers/API/knowledgeIndex", () => ({
  readVersionChunks: mocks.chunks, readFileMetadata: mocks.metadata, updateFileMetadata: mocks.save,
  updateVersionChunk: vi.fn(), deleteVersionChunk: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({ showApiError: vi.fn() }));
const clients: QueryClient[] = [];
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><SpaceIndexEditDialog
    scope={{ identityKey: "user:7", tenantId: 1, managementTenantId: 1, view: "ordinary" }}
    spaceId={7} fileId={11} open onOpenChange={vi.fn()}
  /></QueryClientProvider>);
}
const region = () => screen.getByRole("region", { name: "f118.index_metadata" });
beforeEach(() => {
  vi.resetAllMocks();
  mocks.space.data.metadata_fields = [];
  mocks.target.mockResolvedValue({ file_id: 11 });
  mocks.chunks.mockResolvedValue({ data: [{ text: "Existing chunk", metadata: { document_id: 11, chunk_index: 1 } }], total: 1 });
  mocks.metadata.mockResolvedValue({ user_metadata: {} });
  mocks.save.mockResolvedValue({});
});
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); });
it("replaces the empty metadata save button with an empty state and retains chunk editing", async () => {
  mount();
  await screen.findByText("f118.index_metadata_empty");
  expect(within(region()).queryByRole("button", { name: "save" })).not.toBeInTheDocument();
  expect(screen.getByDisplayValue("Existing chunk")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "save" })).toBeInTheDocument();
});
it("keeps the save action when removing the last existing metadata field", async () => {
  mocks.metadata.mockResolvedValue({ user_metadata: { Author: { field_value: "Alice" } } });
  mount();
  await screen.findByDisplayValue("Alice");
  fireEvent.click(within(region()).getByRole("button", { name: "delete" }));
  fireEvent.click(within(region()).getByRole("button", { name: "save" }));
  await waitFor(() => expect(mocks.save).toHaveBeenCalledWith(11, {}));
});
it("allows adding a configured field before revealing save", async () => {
  mocks.space.data.metadata_fields = [{ field_name: "Author" }];
  mount();
  await screen.findByRole("button", { name: "Author" });
  expect(within(region()).queryByRole("button", { name: "save" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Author" }));
  fireEvent.change(within(region()).getByRole("textbox"), { target: { value: "Alice" } });
  fireEvent.click(within(region()).getByRole("button", { name: "save" }));
  await waitFor(() => expect(mocks.save).toHaveBeenCalledWith(11, { Author: "Alice" }));
});
it("waits for metadata to load before declaring it empty", async () => {
  let resolve!: (value: { user_metadata: Record<string, never> }) => void;
  mocks.metadata.mockReturnValue(new Promise(yes => { resolve = yes; }));
  mount();
  await waitFor(() => expect(mocks.metadata).toHaveBeenCalledOnce());
  expect(screen.queryByText("f118.index_metadata_empty")).not.toBeInTheDocument();
  await act(async () => resolve({ user_metadata: {} }));
  await screen.findByText("f118.index_metadata_empty");
});
