import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { previewFileSplitApi } from "@/controllers/API";
import { knowledgeFilesApi } from "@/controllers/API/knowledgeFiles";
import type { ProcessingDefaults } from "@/controllers/API/knowledgeSpace";
import { FileProcessingPreview } from "./FileProcessingPreview";

vi.mock("@/controllers/API", () => ({
  previewFileSplitApi: vi.fn(() => vi.fn()),
  delChunkInPreviewApi: vi.fn(),
  updatePreviewChunkApi: vi.fn(),
}));
vi.mock("@/controllers/API/knowledgeFiles", () => ({
  knowledgeFilesApi: { getSpaceFilePreview: vi.fn() },
}));
vi.mock("./PreviewFile", () => ({
  default: ({ urlState }: { urlState: { url: string } }) => (
    <span data-testid="original-url">{urlState.url}</span>
  ),
}));
vi.mock("./PreviewParagraph", () => ({
  default: ({
    chunks,
    edit,
  }: {
    chunks: { text: string }[];
    edit: boolean;
  }) => (
    <div data-testid="chunks" data-editable={edit}>
      {chunks.map((chunk) => chunk.text).join("\n")}
    </div>
  ),
}));
vi.mock("./RichPreviewFile", () => ({
  buildMediaUploadPreviewData: vi.fn(),
  isMediaUploadSuffix: () => false,
}));
const defaults: ProcessingDefaults = {
  schema_version: 1,
  document: {
    split_mode: "auto",
    separator: ["\n"],
    separator_rule: ["after"],
    chunk_size: 1000,
    chunk_overlap: 100,
    hierarchy_level: 3,
    append_title: false,
    max_chunk_size: 1000,
    retain_images: 1,
    force_ocr: 1,
    enable_formula: 1,
    filter_page_header_footer: 0,
  },
  table: {
    slice_length: 10,
    header_start_row: 1,
    header_end_row: 1,
    append_header: 1,
  },
};
const originalUrl = "/object/bisheng/original/42.md?signature=example";
const clients: QueryClient[] = [];
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(knowledgeFilesApi.getSpaceFilePreview).mockResolvedValue({
    original_url: originalUrl,
    preview_url: "",
    file_source: "local",
    source_url: "",
    final_url: "",
    web_title: "",
    media_kind: "",
    html_preview_url: "",
  });
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});
function renderPreview() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  const onReady = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/filelib/7?file_id=42"]}>
        <FileProcessingPreview
          scope={{
            identityKey: "user:9",
            tenantId: 1,
            managementTenantId: 1,
            view: "ordinary",
          }}
          spaceId={7}
          fileId={42}
          file={{ file_name: "report.md" }}
          defaults={defaults}
          onReady={onReady}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onReady;
}
const completed = {
  parse_type: "local",
  file_url: originalUrl,
  chunks: [{ text: "New segment", metadata: { chunk_index: 0, page: 1 } }],
  partitions: {},
};
it("resolves an existing file by its authorized identity and enables confirmation only after parsing", async () => {
  const onReady = renderPreview();
  await waitFor(() => expect(previewFileSplitApi).toHaveBeenCalledOnce());
  expect(knowledgeFilesApi.getSpaceFilePreview).toHaveBeenCalledWith(7, 42);
  expect(vi.mocked(previewFileSplitApi).mock.calls[0][0]).toMatchObject({
    knowledge_id: 7,
    chunk_size: 1000,
    file_list: [
      {
        file_path: "knowledge-preview-file:42:original",
        preview_file_id: 42,
        preview_source: "original",
      },
    ],
  });
  expect(onReady).not.toHaveBeenCalledWith(true);
  act(() =>
    vi.mocked(previewFileSplitApi).mock.calls[0][1]("completed", completed),
  );
  expect(onReady).toHaveBeenLastCalledWith(true);
  expect(screen.getByTestId("chunks")).toHaveTextContent("New segment");
  expect(screen.getByTestId("chunks")).toHaveAttribute(
    "data-editable",
    "false",
  );
});
it("shows parse failures beside the original document and retries without allowing a failed preview to confirm", async () => {
  const onReady = renderPreview();
  await waitFor(() => expect(previewFileSplitApi).toHaveBeenCalledOnce());
  act(() =>
    vi.mocked(previewFileSplitApi).mock.calls[0][1]("error", {
      code: 10952,
      message: "404: This resource does not exist",
      data: { exception: "404: This resource does not exist" },
    }),
  );
  expect(screen.getByRole("alert")).toHaveTextContent("previewFailed");
  expect(screen.getByTestId("original-url")).toHaveTextContent(originalUrl);
  expect(onReady).toHaveBeenLastCalledWith(false);
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await waitFor(() => expect(previewFileSplitApi).toHaveBeenCalledTimes(2));
  expect(vi.mocked(previewFileSplitApi).mock.calls[1][0]).toMatchObject({
    cache: false,
    file_list: [
      {
        file_path: "knowledge-preview-file:42:original",
        preview_file_id: 42,
        preview_source: "original",
      },
    ],
  });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(onReady).not.toHaveBeenCalledWith(true);
  act(() =>
    vi.mocked(previewFileSplitApi).mock.calls[1][1]("completed", completed),
  );
  expect(onReady).toHaveBeenLastCalledWith(true);
});
