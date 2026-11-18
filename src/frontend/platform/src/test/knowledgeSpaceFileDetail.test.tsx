import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import useKnowledgeStore from "@/pages/KnowledgePage/useKnowledgeStore";
import { SpaceFileDetail } from "@/pages/KnowledgePage/components/SpaceFileDetail";
import type { FileMetadata } from "@/controllers/API/knowledgeIndex";

const mock = vi.hoisted(() => ({
  preview: vi.fn(),
  previewChunks: vi.fn(),
  info: vi.fn(),
  chunks: vi.fn(),
  boxes: vi.fn(),
  permission: vi.fn(),
  target: vi.fn(),
  save: vi.fn(),
  remove: vi.fn(),
  metadata: vi.fn(),
  schema: vi.fn(),
  confirm: vi.fn(),
  callbacks: [] as ((index: number, text: string) => unknown)[],
}));
vi.mock("@/controllers/request", () => ({ default: {}, showApiError: vi.fn() }));
vi.mock("@/controllers/API/knowledgeFiles", () => ({
  knowledgeFilesApi: { getSpaceFilePreview: mock.preview },
}));
vi.mock("@/controllers/API/knowledgeIndex", () => ({
  readVersionChunks: mock.chunks,
  readFileMetadata: mock.info,
  readFilePartitions: mock.boxes,
  updateVersionChunk: mock.save,
  deleteVersionChunk: mock.remove,
  updateFileMetadata: mock.metadata,
}));
vi.mock("@/controllers/API/permission", () => ({ getMyResourcePermissionsApi: mock.permission }));
vi.mock("@/controllers/API/knowledgeProcessing", () => ({
  readProcessingTarget: mock.target,
  readMetadataSchema: mock.schema,
}));
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: (options: { onOk: () => unknown }) => {
    mock.confirm(options);
    return options.onOk();
  },
}));
vi.mock("@/pages/KnowledgePage/components/SpaceProcessingDialog", () => ({
  SpaceProcessingDialog: ({ open, fileId }: { open: boolean; fileId: number }) =>
    open ? <div role="dialog">process-{fileId}</div> : null,
}));
vi.mock("@/pages/KnowledgePage/components/PreviewFile", () => ({
  default: ({ file, chunks }: { file: { name: string }; chunks: unknown }) => { mock.previewChunks(chunks); return <p>original-{file.name}</p>; },
}));
interface ChunksProps {
  chunks: { text: string; chunkIndex: number }[];
  edit: boolean;
  onChange: (index: number, text: string) => unknown;
  onDel: (index: number) => void;
}
vi.mock("@/pages/KnowledgePage/components/PreviewParagraph", () => ({
  default: ({ chunks, edit, onChange, onDel }: ChunksProps) => {
    mock.callbacks.push(onChange);
    return (
      <div>
        {chunks.map((chunk) => (
          <div key={chunk.chunkIndex}>
            {edit ? (
              <>
                <textarea
                  aria-label={`chunk-${chunk.chunkIndex}`}
                  defaultValue={chunk.text}
                  onBlur={(event) => {
                    void onChange(chunk.chunkIndex, event.target.value);
                  }}
                />
                {chunks.length > 1 && (
                  <button onClick={() => onDel(chunk.chunkIndex)}>delete-{chunk.chunkIndex}</button>
                )}
              </>
            ) : (
              <p>{chunk.text}</p>
            )}
          </div>
        ))}
      </div>
    );
  },
}));
const scope = { identityKey: "user:5", tenantId: 60, managementTenantId: 60, view: "ordinary" as const };
const chunk = {
  text: "Original chunk",
  metadata: { document_id: 890, chunk_index: 0, bbox: '{"chunk_bboxes":[]}' },
};
const info: FileMetadata = {
  id: 89,
  knowledge_id: 7,
  file_name: "Manual.pdf",
  status: 2,
  user_metadata: { Equipment: { field_value: "Pump" } },
};
const clients: QueryClient[] = [];
function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
  });
  clients.push(client);
  const back = vi.fn();
  const draw = (id = 89, currentScope = scope) => (
    <QueryClientProvider client={client}>
      <SpaceFileDetail
        key={JSON.stringify([id, currentScope])}
        scope={currentScope}
        spaceId={7}
        fileId={id}
        onBack={back}
      />
    </QueryClientProvider>
  );
  return { draw, back };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
beforeEach(() => {
  vi.resetAllMocks();
  mock.callbacks.length = 0;
  mock.preview.mockResolvedValue({ original_url: "/Manual.pdf", preview_url: "" });
  mock.info.mockResolvedValue(info);
  mock.chunks.mockResolvedValue({ data: [chunk], total: 1 });
  mock.boxes.mockResolvedValue({});
  mock.permission.mockResolvedValue({ actions: ["visible", "edit"] });
  mock.target.mockImplementation(async (_space: number, id: number) => ({
    file_id: id,
    document_id: 890,
    version_id: 891,
  }));
  mock.save.mockResolvedValue({});
  mock.remove.mockResolvedValue({});
  mock.metadata.mockResolvedValue({});
  mock.schema.mockResolvedValue({ revision: 1, fields: [{ field_name: "Equipment", field_type: "string" }] });
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});

it("restores original preview and editable chunks using the physical file id, including index zero", async () => {
  const f = setup();
  render(f.draw());
  expect(await screen.findByText("original-Manual.pdf")).toBeVisible();
  const input = await screen.findByRole("textbox", { name: "chunk-0" });
  fireEvent.change(input, { target: { value: "Edited chunk" } });
  fireEvent.blur(input);
  await waitFor(() => expect(mock.save).toHaveBeenCalledWith(7, 89, chunk, "Edited chunk"));
  expect(mock.chunks).toHaveBeenCalledWith(7, 89, 1, "");
  expect(mock.preview).toHaveBeenCalledWith(7, 89);
  expect(mock.target).toHaveBeenCalledWith(7, 89);
});

it("keeps visible-only preview and chunks without editable controls or processing-target requests", async () => {
  mock.permission.mockResolvedValue({ actions: ["visible"] });
  const f = setup();
  render(f.draw());
  expect(await screen.findByText("original-Manual.pdf")).toBeVisible();
  expect(await screen.findByText("Original chunk")).toBeVisible();
  expect(screen.queryByRole("textbox", { name: "chunk-0" })).toBeNull();
  expect(screen.queryByRole("button", { name: "metadialog.title" })).toBeNull();
  expect(mock.target).not.toHaveBeenCalled();
  expect(mock.save).not.toHaveBeenCalled();
});

it("searches chunks at the first page and preserves the file target for deletion and resplitting", async () => {
  mock.chunks.mockResolvedValue({
    data: [chunk, { ...chunk, text: "Second", metadata: { ...chunk.metadata, chunk_index: 1 } }],
    total: 2,
  });
  const f = setup();
  render(f.draw());
  await screen.findByRole("textbox", { name: "chunk-0" });
  fireEvent.change(screen.getByRole("searchbox", { name: "segment.searchSegments" }), {
    target: { value: "pump" },
  });
  await waitFor(() => expect(mock.chunks).toHaveBeenCalledWith(7, 89, 1, "pump"));
  fireEvent.click(await screen.findByRole("button", { name: "delete-0" }));
  await waitFor(() => expect(mock.remove).toHaveBeenCalledWith(7, 89, chunk));
  expect(mock.confirm).toHaveBeenCalledOnce();
  fireEvent.click(await screen.findByRole("button", { name: "segment.adjustStrategy" }));
  expect(await screen.findByRole("dialog")).toHaveTextContent("process-89");
});

it("edits metadata for the same physical file and saves through the existing endpoint", async () => {
  const f = setup();
  render(f.draw());
  fireEvent.click(await screen.findByRole("button", { name: "metadialog.title" }));
  const input = await screen.findByRole("textbox", { name: "Equipment" });
  expect(input).toHaveValue("Pump");
  fireEvent.change(input, { target: { value: "Pump 2" } });
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(mock.metadata).toHaveBeenCalledWith(89, { Equipment: "Pump 2" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("retires old chunk responses and old editor callbacks after switching tenant or file", async () => {
  const old = deferred<{ data: (typeof chunk)[]; total: number }>();
  const f = setup();
  const view = render(f.draw());
  await screen.findByRole("textbox", { name: "chunk-0" });
  const retiredChange = mock.callbacks[mock.callbacks.length - 1];
  mock.chunks
    .mockReturnValueOnce(old.promise)
    .mockResolvedValueOnce({ data: [{ ...chunk, text: "Current tenant chunk" }], total: 1 });
  view.rerender(f.draw(90));
  await waitFor(() => expect(mock.chunks).toHaveBeenCalledWith(7, 90, 1, ""));
  view.rerender(f.draw(91, { ...scope, tenantId: 61, managementTenantId: 61 }));
  expect(await screen.findByRole("textbox", { name: "chunk-0" })).toHaveValue("Current tenant chunk");
  await act(async () => {
    old.resolve({ data: [{ ...chunk, text: "Retired file chunk" }], total: 1 });
    await retiredChange(0, "stale write");
  });
  expect(screen.getByRole("textbox", { name: "chunk-0" })).toHaveValue("Current tenant chunk");
  expect(mock.save).not.toHaveBeenCalled();
});

it("does not request file info or chunks before the scoped preview succeeds, and allows retry", async () => {
  mock.preview
    .mockRejectedValueOnce(new Error("denied"))
    .mockResolvedValueOnce({ original_url: "/Manual.pdf", preview_url: "" });
  const f = setup();
  render(f.draw());
  fireEvent.click(await screen.findByRole("button", { name: "retry" }));
  expect(mock.info).not.toHaveBeenCalled();
  expect(mock.chunks).not.toHaveBeenCalled();
  expect(await screen.findByRole("textbox", { name: "chunk-0" })).toHaveValue("Original chunk");
});

it("retains an unsaved chunk after a failed write and retries the same physical target", async () => {
  mock.save.mockRejectedValueOnce(new Error("save failed")).mockResolvedValueOnce({});
  const f = setup();
  render(f.draw());
  const input = await screen.findByRole("textbox", { name: "chunk-0" });
  fireEvent.change(input, { target: { value: "Unsaved draft" } });
  fireEvent.blur(input);
  expect(await screen.findByText("detail.save_failed")).toBeVisible();
  expect(screen.getByText("Unsaved draft")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await waitFor(() => expect(mock.save).toHaveBeenCalledTimes(2));
  expect(mock.save.mock.calls[1]).toEqual(mock.save.mock.calls[0]);
  await waitFor(() => expect(screen.queryByText("detail.save_failed")).toBeNull());
});

it("does not refresh or write into the next file after an earlier save completes late", async () => {
  const pending = deferred<unknown>();
  mock.save.mockReturnValueOnce(pending.promise);
  const f = setup();
  const view = render(f.draw());
  const input = await screen.findByRole("textbox", { name: "chunk-0" });
  fireEvent.change(input, { target: { value: "Earlier file change" } });
  fireEvent.blur(input);
  await waitFor(() => expect(mock.save).toHaveBeenCalledOnce());
  view.rerender(f.draw(90));
  await screen.findByRole("textbox", { name: "chunk-0" });
  const reads = mock.chunks.mock.calls.length;
  await act(async () => pending.resolve({}));
  expect(mock.chunks).toHaveBeenCalledTimes(reads);
  expect(mock.save).toHaveBeenCalledTimes(1);
});

it("displays legacy chunks with malformed bbox data through a safe preview fallback", async () => {
  mock.chunks.mockResolvedValue({ data: [{ ...chunk, metadata: { ...chunk.metadata, bbox: "invalid json" } }], total: 1 });
  const f = setup(); render(f.draw());
  await screen.findByRole("textbox", { name: "chunk-0" });
  await waitFor(() => expect(mock.previewChunks).toHaveBeenCalledWith([{ text: "Original chunk", chunkIndex: 0, bbox: "" }]));
});

it("clears the previous chunk's selected boxes before editing a different chunk", async () => {
  const next = { ...chunk, text: "Second", metadata: { ...chunk.metadata, chunk_index: 1 } };
  mock.chunks.mockResolvedValue({ data: [chunk, next], total: 2 });
  const f = setup(); render(f.draw());
  const input = await screen.findByRole("textbox", { name: "chunk-1" });
  act(() => useKnowledgeStore.getState().setSelectedChunkIndex(0));
  act(() => useKnowledgeStore.getState().setSelectedBbox([{ page: 1, bbox: [1, 2, 3, 4] }]));
  act(() => useKnowledgeStore.getState().setSelectedChunkIndex(1));
  expect(useKnowledgeStore.getState().selectedBbox).toEqual([]);
  fireEvent.change(input, { target: { value: "Second edit" } }); fireEvent.blur(input);
  await waitFor(() => expect(mock.save).toHaveBeenCalledWith(7, 89, next, "Second edit"));
  await waitFor(() => expect(screen.getByRole("textbox", { name: "chunk-0" })).not.toBeDisabled());
  act(() => useKnowledgeStore.getState().setSelectedBbox([{ page: 2, bbox: [2, 3, 4, 5] }]));
  await act(async () => { await mock.callbacks[mock.callbacks.length - 1](0, "Delayed first edit"); });
  expect(mock.save).toHaveBeenCalledWith(7, 89, chunk, "Delayed first edit");
});
