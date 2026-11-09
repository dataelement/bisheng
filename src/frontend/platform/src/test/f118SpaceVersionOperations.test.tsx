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
import { locationContext } from "@/contexts/locationContext";
import { SpaceVersionHistorySheet } from "@/pages/KnowledgePage/components/SpaceVersionHistorySheet";
import { SpaceVersionRelationPanel } from "@/pages/KnowledgePage/components/SpaceVersionRelationPanel";
import { SpaceSimilarDocumentPanel } from "@/pages/KnowledgePage/components/SpaceSimilarDocumentPanel";
import { SpaceVersionUploadPanel } from "@/pages/KnowledgePage/components/SpaceVersionUploadPanel";
import { SpaceDirectoryRow } from "@/pages/KnowledgePage/components/SpaceDirectoryRow";
import type {
  KnowledgeVersionsApi,
  SpaceVersionHistory,
} from "@/controllers/API/knowledgeVersions";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  confirm: vi.fn(),
  error: vi.fn(),
  upload: vi.fn(),
  register: vi.fn(),
  children: vi.fn(),
  preview: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({
  default: { get: mocks.get },
  showApiError: mocks.error,
}));
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: mocks.confirm,
}));
vi.mock("@/controllers/API/knowledgeUploads", () => ({
  knowledgeUploadsApi: {
    uploadSpaceFile: mocks.upload,
    registerSpaceFiles: mocks.register,
  },
}));
vi.mock("@/controllers/API/knowledgeSpace", () => ({
  knowledgeSpaceApi: { listChildren: mocks.children },
}));
vi.mock("@/controllers/API/knowledgeFiles", () => ({
  knowledgeFilesApi: { getSpaceFilePreview: mocks.preview },
}));
vi.mock("@/pages/KnowledgePage/components/SpaceFileTools", () => ({
  SpaceFileTools: () => null,
}));
vi.mock("@/pages/KnowledgePage/components/PreviewFile", () => ({
  default: ({ file }: { file: { id: number } }) => (
    <div>preview-file-{file.id}</div>
  ),
}));
const scope: KnowledgeQueryScope = {
  identityKey: "user7/credential-a",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary",
};
const history = (): SpaceVersionHistory => ({
  document_id: 41,
  knowledge_id: 7,
  title: "Current document",
  doc_code: "DOC41",
  current_primary_version_no: 2,
  versions: [
    {
      version_id: 51,
      version_no: 1,
      knowledge_file_id: 11,
      is_primary: false,
      original_file_name: "old.md",
      file_code: null,
      uploader_name: null,
      uploader_id: null,
      upload_time: null,
      status: 2,
    },
    {
      version_id: 52,
      version_no: 2,
      knowledge_file_id: 12,
      is_primary: true,
      original_file_name: "primary.md",
      file_code: null,
      uploader_name: null,
      uploader_id: null,
      upload_time: null,
      status: 2,
    },
  ],
});
const clients: QueryClient[] = [];
function api(): KnowledgeVersionsApi {
  return {
    getSpaceFileVersions: vi.fn().mockImplementation(async () => history()),
    setSpacePrimaryVersion: vi
      .fn()
      .mockResolvedValue({ document_id: 41, new_primary_version_no: 1 }),
    deleteSpaceFileVersion: vi.fn().mockResolvedValue({}),
    linkSpaceFileVersion: vi
      .fn()
      .mockResolvedValue({ document_id: 61, new_version_no: 3 }),
    mergeSpaceFileVersion: vi
      .fn()
      .mockResolvedValue({ document_id: 41, new_version_no: 3 }),
    dismissSpaceSimilarFile: vi.fn().mockResolvedValue({}),
    getVersionRecommendations: vi.fn().mockResolvedValue([]),
    searchVersionDocuments: vi.fn().mockResolvedValue({
      data: [],
      has_more: false,
      next_cursor: null,
      page_size: 40,
    }),
  };
}
function mount(content: React.ReactNode, enabled = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
  });
  clients.push(client);
  const wrap = (next: React.ReactNode, flag = enabled) => (
    <QueryClientProvider client={client}>
      <locationContext.Provider
        value={
          {
            appConfig: {
              versionManagementEnabled: flag,
              uploadFileMaxSize: 50,
            },
          } as React.ContextType<typeof locationContext>
        }
      >
        {next}
      </locationContext.Provider>
    </QueryClientProvider>
  );
  const result = render(wrap(content));
  return {
    ...result,
    client,
    update: (next: React.ReactNode, flag = enabled) =>
      result.rerender(wrap(next, flag)),
  };
}
async function confirmLast() {
  const confirmation = mocks.confirm.mock.lastCall?.[0];
  expect(confirmation).toBeDefined();
  await act(async () => {
    await confirmation.onOk(vi.fn());
  });
}
beforeEach(() => vi.resetAllMocks());
afterEach(() => {
  cleanup();
  clients.forEach((client) => client.clear());
  clients.length = 0;
});

it("mounts the real version sheet for a single-version file only under the original feature flag", async () => {
  mocks.get.mockResolvedValue(history());
  const row = (
    <table>
      <tbody>
        <SpaceDirectoryRow
          scope={scope}
          spaceId={7}
          parentId={9}
          item={{
            id: 12,
            knowledge_id: 7,
            file_type: 1,
            file_name: "primary.md",
            is_multi_version: false,
            status: 2,
          }}
          open
          actions={["visible"]}
          loading={false}
          error={false}
          onMenu={vi.fn()}
          onOpen={vi.fn()}
          onPreview={vi.fn()}
          onRename={vi.fn()}
          onDownload={vi.fn()}
        />
      </tbody>
    </table>
  );
  const view = mount(row);
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "f118.version_history" }),
  );
  expect(
    await screen.findByRole("button", { name: "versions.new_version" }),
  ).toBeVisible();
  view.update(row, false);
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "versions.new_version" }),
    ).not.toBeInTheDocument(),
  );
  expect(
    screen.queryByRole("menuitem", { name: "f118.version_history" }),
  ).not.toBeInTheDocument();
});

it("runs the actual historical version endpoints and rereads history, without adding an edit/role gate", async () => {
  const ports = api();
  mount(
    <SpaceVersionHistorySheet
      scope={scope}
      spaceId={7}
      parentId={9}
      fileId={12}
      open
      onOpenChange={vi.fn()}
      api={ports}
    />,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "versions.set_primary" }),
  );
  expect(ports.setSpacePrimaryVersion).not.toHaveBeenCalled();
  await confirmLast();
  expect(ports.setSpacePrimaryVersion).toHaveBeenCalledExactlyOnceWith(
    51,
    expect.any(AbortSignal),
  );
  await waitFor(() =>
    expect(ports.getSpaceFileVersions).toHaveBeenCalledTimes(2),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "versions.delete_history" }),
  );
  await confirmLast();
  expect(ports.deleteSpaceFileVersion).toHaveBeenCalledExactlyOnceWith(
    51,
    expect.any(AbortSignal),
  );
});

it("keeps feature-off history read-only and rejects a foreign-space response", async () => {
  const ports = api();
  const view = mount(
    <SpaceVersionHistorySheet
      scope={scope}
      spaceId={7}
      parentId={null}
      fileId={12}
      open
      onOpenChange={vi.fn()}
      api={ports}
    />,
    false,
  );
  await screen.findByText("Current document");
  expect(
    screen.queryByRole("button", { name: "versions.new_version" }),
  ).not.toBeInTheDocument();
  view.unmount();
  vi.mocked(ports.getSpaceFileVersions).mockResolvedValue({
    ...history(),
    knowledge_id: 202,
  });
  mount(
    <SpaceVersionHistorySheet
      scope={scope}
      spaceId={7}
      parentId={null}
      fileId={12}
      open
      onOpenChange={vi.fn()}
      api={ports}
    />,
  );
  await screen.findByRole("alert");
  expect(screen.queryByText("Current document")).not.toBeInTheDocument();
});

it("does not replay an uncertain history mutation and retires old confirmations on identity or flag change", async () => {
  const ports = api(),
    error = { status_code: 500, status_message: "ACK lost" };
  vi.mocked(ports.deleteSpaceFileVersion).mockRejectedValue(error);
  const props = {
    scope,
    spaceId: 7,
    parentId: null,
    fileId: 12,
    open: true,
    onOpenChange: vi.fn(),
    api: ports,
  };
  const view = mount(<SpaceVersionHistorySheet {...props} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "versions.delete_history" }),
  );
  await confirmLast();
  expect(await screen.findByText("versions.uncertain")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "versions.delete_history" }),
  ).toBeDisabled();
  expect(ports.deleteSpaceFileVersion).toHaveBeenCalledTimes(1);
  expect(mocks.error).toHaveBeenCalledWith(error);
  await confirmLast();
  expect(ports.deleteSpaceFileVersion).toHaveBeenCalledTimes(1);
  view.update(
    <SpaceVersionHistorySheet
      {...props}
      scope={{ ...scope, identityKey: "user8/credential-b" }}
    />,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "versions.set_primary" }),
  );
  const pending = mocks.confirm.mock.lastCall![0];
  view.update(<SpaceVersionHistorySheet {...props} />, false);
  expect(pending.signal.aborted).toBe(true);
  await act(async () => {
    await pending.onOk(vi.fn());
  });
  expect(ports.setSpacePrimaryVersion).not.toHaveBeenCalled();
});

it("keeps cursor search and merge direction exact, and previews only the authorized primary file ID", async () => {
  const ports = api(),
    onChanged = vi.fn().mockResolvedValue(undefined);
  const candidate = {
    document_id: 61,
    title: "Candidate",
    current_primary_version_no: 1,
    primary_knowledge_file_id: 99,
  };
  vi.mocked(ports.searchVersionDocuments)
    .mockResolvedValueOnce({
      data: [candidate],
      has_more: true,
      next_cursor: "page2",
      page_size: 40,
    })
    .mockResolvedValueOnce({
      data: [{ ...candidate, document_id: 62, title: "Next candidate" }],
      has_more: false,
      next_cursor: null,
      page_size: 40,
    });
  mocks.preview.mockResolvedValue({
    preview_url: "https://example.invalid/preview",
    original_url: "",
  });
  mount(
    <SpaceVersionRelationPanel
      scope={scope}
      spaceId={7}
      fileId={12}
      mode="merge"
      api={ports}
      onChanged={onChanged}
    />,
  );
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "Candidate" },
  });
  fireEvent.click(screen.getByRole("button", { name: "versions.search" }));
  await screen.findByText("Candidate");
  expect(ports.searchVersionDocuments).toHaveBeenCalledWith(
    7,
    12,
    "Candidate",
    true,
    undefined,
    expect.any(AbortSignal),
  );
  fireEvent.click(screen.getByRole("button", { name: "versions.load_more" }));
  await screen.findByText("Next candidate");
  expect(ports.searchVersionDocuments).toHaveBeenLastCalledWith(
    7,
    12,
    "Candidate",
    true,
    "page2",
    expect.any(AbortSignal),
  );
  fireEvent.click(
    screen.getAllByRole("button", { name: "versions.preview" })[0],
  );
  expect(await screen.findByText("preview-file-99")).toBeVisible();
  expect(mocks.preview).toHaveBeenCalledExactlyOnceWith(7, 99);
  fireEvent.click(screen.getAllByRole("button", { name: "versions.merge" })[0]);
  await confirmLast();
  expect(ports.mergeSpaceFileVersion).toHaveBeenCalledExactlyOnceWith(
    12,
    61,
    expect.any(AbortSignal),
  );
  expect(ports.linkSpaceFileVersion).not.toHaveBeenCalled();
  expect(onChanged).toHaveBeenCalledTimes(1);
});

it("keeps similar as-version in the original link direction, and keep-both uses dismissal", async () => {
  const ports = api(),
    changed = vi.fn().mockResolvedValue(undefined);
  vi.mocked(ports.getVersionRecommendations).mockResolvedValue([
    {
      target_document_id: 61,
      title: "Similar",
      current_primary_version_no: 2,
      similarity: 0.98,
    },
  ]);
  mount(
    <SpaceSimilarDocumentPanel
      scope={scope}
      spaceId={7}
      fileId={12}
      api={ports}
      onChanged={changed}
    />,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "versions.as_version" }),
  );
  await confirmLast();
  expect(ports.linkSpaceFileVersion).toHaveBeenCalledExactlyOnceWith(
    12,
    61,
    expect.any(AbortSignal),
  );
  expect(ports.mergeSpaceFileVersion).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "versions.keep_two" }));
  await confirmLast();
  expect(ports.dismissSpaceSimilarFile).toHaveBeenCalledExactlyOnceWith(
    12,
    expect.any(AbortSignal),
  );
});

it("registers once in the real parent, waits for actual processing success, then requires explicit link confirmation", async () => {
  const ports = api(),
    changed = vi.fn().mockResolvedValue(undefined),
    busy = vi.fn();
  const row = {
    id: 99,
    knowledge_id: 7,
    file_type: 1,
    file_name: "new.md",
    status: 5,
  };
  mocks.upload.mockResolvedValue({ file_path: "staged/new.md" });
  mocks.register.mockResolvedValue([row]);
  let resolve!: (value: unknown) => void;
  mocks.children.mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  mount(
    <SpaceVersionUploadPanel
      scope={scope}
      spaceId={7}
      parentId={9}
      documentId={41}
      api={ports}
      onChanged={changed}
      onBusyChange={busy}
    />,
  );
  fireEvent.change(screen.getByLabelText("versions.choose_file"), {
    target: { files: [new File(["new"], "new.md", { type: "text/markdown" })] },
  });
  await waitFor(() =>
    expect(mocks.register).toHaveBeenCalledExactlyOnceWith(
      7,
      { file_path: ["staged/new.md"], parent_id: 9 },
      expect.any(AbortSignal),
    ),
  );
  expect(ports.linkSpaceFileVersion).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", { name: "versions.confirm_new_version" }),
  ).toBeDisabled();
  await act(async () => {
    resolve({ data: [{ ...row, status: 2 }], has_more: false });
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "versions.confirm_new_version" }),
  );
  expect(ports.linkSpaceFileVersion).not.toHaveBeenCalled();
  await confirmLast();
  expect(ports.linkSpaceFileVersion).toHaveBeenCalledExactlyOnceWith(
    99,
    41,
    expect.any(AbortSignal),
  );
  expect(mocks.register).toHaveBeenCalledTimes(1);
  expect(changed).toHaveBeenCalledTimes(1);
});

it("retains the uploaded standalone file on registration ACK loss without automatic registration or linking", async () => {
  const ports = api();
  mocks.upload.mockResolvedValue({ file_path: "staged/new.md" });
  mocks.register.mockRejectedValue(new Error("ACK unknown"));
  mount(
    <SpaceVersionUploadPanel
      scope={scope}
      spaceId={7}
      parentId={null}
      documentId={41}
      api={ports}
      onChanged={vi.fn()}
      onBusyChange={vi.fn()}
    />,
  );
  const input = screen.getByLabelText("versions.choose_file");
  fireEvent.change(input, { target: { files: [new File(["new"], "new.md")] } });
  await screen.findByText("versions.uncertain");
  expect(input).toBeDisabled();
  expect(mocks.register).toHaveBeenCalledTimes(1);
  expect(ports.linkSpaceFileVersion).not.toHaveBeenCalled();
});
