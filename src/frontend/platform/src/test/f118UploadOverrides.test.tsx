import "@testing-library/jest-dom/vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ProcessingDefaults } from "@/controllers/API/knowledgeSpace";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { SpaceFileUploadPanel } from "@/pages/KnowledgePage/components/SpaceFileUploadPanel";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  error: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({
  default: mocks,
  showApiError: mocks.error,
}));
vi.mock("@/contexts/locationContext", async () => ({
  locationContext: (await import("react")).createContext({
    appConfig: { enableEtl4lm: true, enableMediaUpload: true },
  }),
}));
vi.mock("@/pages/KnowledgePage/components/FileUploadSplitStrategy", () => ({
  default: () => null,
}));
vi.mock("@/pages/KnowledgePage/components/KnowledgeTooltip", () => ({
  KnowledgeHint: () => null,
}));
const defaults: ProcessingDefaults = {
  schema_version: 1,
  document: {
    split_mode: "custom",
    separator: ["\\n", ""],
    separator_rule: ["after", "after"],
    chunk_size: 300,
    chunk_overlap: 20,
    hierarchy_level: 3,
    append_title: false,
    max_chunk_size: 600,
    retain_images: 1,
    force_ocr: 0,
    enable_formula: 0,
    filter_page_header_footer: 1,
  },
  table: {
    slice_length: 10,
    header_start_row: 1,
    header_end_row: 2,
    append_header: 0,
  },
};
const settings = () => ({
  space_id: 7,
  config_version: 4,
  saved_defaults: null,
  effective_defaults: structuredClone(defaults),
});
const scope: KnowledgeQueryScope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary",
};
const clients: QueryClient[] = [];
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  const element = (value: KnowledgeQueryScope) => (
    <QueryClientProvider client={client}>
      <SpaceFileUploadPanel scope={value} spaceId={7} parentId={9} />
    </QueryClientProvider>
  );
  const result = render(element(scope));
  return {
    ...result,
    update: (value: KnowledgeQueryScope) => result.rerender(element(value)),
  };
}
async function drop(name = "report.md") {
  await act(async () =>
    fireEvent.change(document.querySelector('input[type="file"]')!, {
      target: { files: [new File(["content"], name)] },
    }),
  );
}
async function customize() {
  fireEvent.click(
    screen.getByRole("checkbox", { name: "f118.upload_temporary" }),
  );
  await screen.findByRole("spinbutton", { name: "splitLength" });
}
const registers = () =>
  mocks.post.mock.calls.filter(([url]) => url.endsWith("/files"));
beforeEach(() => {
  vi.resetAllMocks();
  mocks.get.mockImplementation(async (url: string) => {
    if (url.endsWith("/upload-settings")) return settings();
    throw new Error(`unexpected read ${url}`);
  });
  mocks.post.mockImplementation(async (url: string, body: FormData) =>
    url.endsWith("/files")
      ? [{ id: 81, knowledge_id: 7, file_name: "report.md", status: 2 }]
      : { file_path: `tmp/${(body.get("file") as File).name}`, repeat: false },
  );
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});

it("inherits without reading edit-only defaults or sending overrides", async () => {
  mount();
  await drop();
  await waitFor(() => expect(registers()).toHaveLength(1));
  expect(registers()[0][1]).toEqual({
    file_path: ["tmp/report.md"],
    parent_id: 9,
  });
  expect(mocks.get).not.toHaveBeenCalled();
  expect(mocks.put).not.toHaveBeenCalled();
});

it("fixes actual folder rules and both document/table drafts per drop and retry", async () => {
  let resolve!: (value: { file_path: string; repeat: boolean }) => void;
  const staged = new Promise<{ file_path: string; repeat: boolean }>((yes) => {
    resolve = yes;
  });
  const failure = { status_code: 10999 };
  let attempts = 0;
  mocks.post.mockImplementation(async (url: string) => {
    if (!url.endsWith("/files")) return staged;
    if (++attempts === 1) throw failure;
    return [{ id: 81, knowledge_id: 7, file_name: "report.md", status: 2 }];
  });
  mount();
  await customize();
  expect(mocks.get).toHaveBeenCalledExactlyOnceWith(
    "/api/v1/knowledge/space/7/files/upload-settings",
    { params: { parent_id: 9 }, signal: expect.any(AbortSignal) },
  );
  fireEvent.change(screen.getByRole("spinbutton", { name: "splitLength" }), {
    target: { value: "420" },
  });
  fireEvent.mouseDown(screen.getByRole("tab", { name: "f118.tables" }), {
    button: 0,
    ctrlKey: false,
  });
  fireEvent.change(
    screen.getByRole("spinbutton", { name: "maxRowsPerSegment" }),
    {
      target: { value: "25" },
    },
  );
  await drop();
  fireEvent.change(
    screen.getByRole("spinbutton", { name: "maxRowsPerSegment" }),
    {
      target: { value: "99" },
    },
  );
  await act(async () => resolve({ file_path: "tmp/fixed", repeat: false }));
  await waitFor(() => expect(registers()).toHaveLength(1));
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await waitFor(() => expect(registers()).toHaveLength(2));
  const expected = {
    document: { ...defaults.document, chunk_size: 420 },
    table: { ...defaults.table, slice_length: 25 },
  };
  expect(registers().map((call) => call[1].overrides)).toEqual([
    expected,
    expected,
  ]);
  expect(
    mocks.post.mock.calls.filter(([url]) => url.endsWith("/upload/7")),
  ).toHaveLength(1);
  expect(mocks.put).not.toHaveBeenCalled();
  expect(mocks.error).toHaveBeenCalledWith(failure);
});

it("rejects incomplete drafts before staging and can explicitly inherit", async () => {
  mount();
  await customize();
  fireEvent.change(screen.getByRole("spinbutton", { name: "splitLength" }), {
    target: { value: "" },
  });
  await drop();
  expect(mocks.post).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("checkbox", { name: "f118.upload_temporary" }),
  );
  await drop();
  await waitFor(() => expect(registers()).toHaveLength(1));
  expect(registers()[0][1]).not.toHaveProperty("overrides");
});

it("does not send document/table overrides for specialized media", async () => {
  mount();
  await customize();
  await drop("recording.mp3");
  await waitFor(() => expect(registers()).toHaveLength(1));
  expect(registers()[0][1]).not.toHaveProperty("overrides");
});

it("keeps failed settings reads explicit with real retry and no early upload", async () => {
  const error = { status_code: 19000 };
  mocks.get.mockRejectedValueOnce(error).mockResolvedValueOnce(settings());
  mount();
  fireEvent.click(
    screen.getByRole("checkbox", { name: "f118.upload_temporary" }),
  );
  await screen.findByText("f118.load_failed");
  await drop();
  expect(mocks.post).not.toHaveBeenCalled();
  expect(mocks.error).toHaveBeenCalledWith(error);
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await screen.findByRole("spinbutton", { name: "splitLength" });
  await drop();
  await waitFor(() => expect(registers()).toHaveLength(1));
});

it("retires a late rules read across tenant scope changes", async () => {
  let resolve!: (value: ReturnType<typeof settings>) => void;
  mocks.get.mockReturnValue(
    new Promise<ReturnType<typeof settings>>((yes) => {
      resolve = yes;
    }),
  );
  const view = mount();
  fireEvent.click(
    screen.getByRole("checkbox", { name: "f118.upload_temporary" }),
  );
  await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1));
  const signal = mocks.get.mock.calls[0][1].signal as AbortSignal;
  view.update({ ...scope, tenantId: 202, managementTenantId: 202 });
  await act(async () => resolve(settings()));
  expect(signal.aborted).toBe(true);
  expect(
    screen.queryByRole("spinbutton", { name: "splitLength" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("checkbox", { name: "f118.upload_temporary" }),
  ).not.toBeChecked();
});
