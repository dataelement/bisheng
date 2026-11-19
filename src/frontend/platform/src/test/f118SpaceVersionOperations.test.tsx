import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { locationContext } from "@/contexts/locationContext";
import { SpaceVersionHistorySheet } from "@/pages/KnowledgePage/components/SpaceVersionHistorySheet";
import { SpaceVersionRelationPanel } from "@/pages/KnowledgePage/components/SpaceVersionRelationPanel";
import { SpaceSimilarDocumentDialog } from "@/pages/KnowledgePage/components/SpaceSimilarDocumentDialog";
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
  SpaceFileTools: ({ children }: { children?: (items: React.ReactNode) => React.ReactNode }) => children?.(null) ?? null,
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
beforeEach(() => {
  vi.resetAllMocks();
  mocks.get.mockResolvedValue({ actions: ["visible", "edit", "upload_file", "delete"] });
});
afterEach(() => {
  cleanup();
  clients.forEach((client) => client.clear());
  clients.length = 0;
});

it.each(["visible", "error", "pending"])("keeps version history readable without mutation entries when permission is %s", async state => {
  if (state === "error") mocks.get.mockRejectedValue({ status_code: 25008 });
  else if (state === "pending") mocks.get.mockReturnValue(new Promise(() => undefined));
  else mocks.get.mockResolvedValue({ actions: ["visible"] });
  const ports = api();
  mount(<SpaceVersionHistorySheet scope={scope} spaceId={7} parentId={9} fileId={12} open onOpenChange={vi.fn()} api={ports} />);
  expect(await screen.findByText("old.md")).toBeVisible();
  for (const name of ["versions.new_version", "versions.merge", "versions.set_primary", "versions.delete_history"]) {
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  }
  expect(ports.deleteSpaceFileVersion).not.toHaveBeenCalled();
  expect(ports.setSpacePrimaryVersion).not.toHaveBeenCalled();
});

it("checks upload on the current folder and delete on the historical physical file", async () => {
  mocks.get.mockImplementation(async (url: string) => ({ actions:
    url.includes("knowledge_space/7/") ? ["visible", "edit"] : ["visible"],
  }));
  const ports = api();
  mount(<SpaceVersionHistorySheet scope={scope} spaceId={7} parentId={9} fileId={12} open onOpenChange={vi.fn()} api={ports} />);
  expect(await screen.findByRole("button", { name: "versions.set_primary" })).toBeVisible();
  await waitFor(() => expect(mocks.get).toHaveBeenCalledWith(expect.stringContaining("knowledge_file/11/my-permissions"), undefined));
  expect(mocks.get).toHaveBeenCalledWith(expect.stringContaining("folder/9/my-permissions"), undefined);
  expect(screen.queryByRole("button", { name: "versions.new_version" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "versions.delete_history" })).not.toBeInTheDocument();
});

it("ignores late version management grants from a retired tenant view", async () => {
  let resolve!: (value: { actions: string[] }) => void;
  mocks.get.mockReturnValue(new Promise<{ actions: string[] }>(done => { resolve = done; }));
  const ports = api();
  const content = (target = scope) => <SpaceVersionHistorySheet scope={target} spaceId={7} parentId={9} fileId={12} open onOpenChange={vi.fn()} api={ports} />;
  const view = mount(content());
  await screen.findByText("old.md");
  mocks.get.mockResolvedValue({ actions: ["visible"] });
  view.update(content({ ...scope, tenantId: 202, managementTenantId: 202 }));
  await act(async () => { resolve({ actions: ["visible", "edit", "upload_file", "delete"] }); });
  await screen.findByText("old.md");
  for (const name of ["versions.new_version", "versions.merge", "versions.set_primary", "versions.delete_history"]) {
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  }
});

it("opens version management for a parsed single-version file only with space edit and the feature flag", async () => {
  mocks.get.mockImplementation(async (url: string) => url.endsWith("/my-permissions") ? { actions: ["edit", "upload_file"] } : history());
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
    await screen.findByRole("menuitem", { name: "versions.manage" }),
  );
  expect(await screen.findByRole("dialog")).toHaveClass("left-1/2", "top-1/2", "max-w-[min(720px,90vw)]");
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
    screen.queryByRole("menuitem", { name: "versions.manage" }),
  ).not.toBeInTheDocument();
});

it("runs permitted historical version endpoints and rereads history", async () => {
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

it("shares the client single-file merge direction, search scope and direct dismissal", async () => {
  const ports = api(),
    changed = vi.fn().mockResolvedValue(undefined),
    onOpenChange = vi.fn();
  vi.mocked(ports.getVersionRecommendations).mockResolvedValue([
    {
      target_document_id: 61,
      title: "Similar",
      current_primary_version_no: 2,
      similarity: 0.98,
    },
  ]);
  const dialog = (
    <SpaceSimilarDocumentDialog
      scope={scope}
      spaceId={7}
      fileId={12}
      file={{ id: 12, name: "primary.md", version_no: 1, user_name: "Uploader" }}
      open
      onOpenChange={onOpenChange}
      api={ports}
      onChanged={changed}
    />
  );
  const view = mount(dialog);
  await screen.findByText("Similar");
  expect(ports.getVersionRecommendations).toHaveBeenCalledExactlyOnceWith(
    12,
    true,
    expect.any(AbortSignal),
  );
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "source" } });
  fireEvent.click(screen.getByRole("button", { name: "search_button" }));
  await waitFor(() => expect(ports.searchVersionDocuments).toHaveBeenCalledExactlyOnceWith(
    7,
    12,
    "source",
    true,
    undefined,
    expect.any(AbortSignal),
  ));
  fireEvent.click(
    screen.getByRole("button", { name: "btn_link_as_new_version" }),
  );
  const confirmation = await screen.findByRole("alertdialog");
  expect(confirmation).toHaveTextContent("confirm_merge_description");
  fireEvent.click(within(confirmation).getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(ports.mergeSpaceFileVersion).toHaveBeenCalledExactlyOnceWith(
    12,
    61,
    expect.any(AbortSignal),
  ));
  expect(ports.linkSpaceFileVersion).not.toHaveBeenCalled();
  expect(changed).toHaveBeenCalledTimes(1);
  expect(onOpenChange).toHaveBeenCalledWith(false);
  view.unmount();
  mount(dialog);
  fireEvent.click(await screen.findByRole("button", { name: "btn_dismiss" }));
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(2));
  expect(ports.dismissSpaceSimilarFile).toHaveBeenCalledExactlyOnceWith(
    12,
    expect.any(AbortSignal),
  );
  expect(mocks.confirm).not.toHaveBeenCalled();
});

it("retires similar-document requests on scope changes and closes when the feature is disabled", async () => {
  const ports = api();
  let resolve!: (rows: Awaited<ReturnType<KnowledgeVersionsApi["getVersionRecommendations"]>>) => void;
  const previous = new Promise<Awaited<ReturnType<KnowledgeVersionsApi["getVersionRecommendations"]>>>((done) => { resolve = done; });
  vi.mocked(ports.getVersionRecommendations).mockReturnValueOnce(previous).mockResolvedValue([
    { target_document_id: 62, title: "New scope candidate", current_primary_version_no: 1, similarity: 0.97 },
  ]);
  const dialog = (currentScope = scope) => (
    <SpaceSimilarDocumentDialog
      scope={currentScope}
      spaceId={7}
      fileId={12}
      file={{ id: 12, name: "primary.md" }}
      open
      onOpenChange={vi.fn()}
      api={ports}
    />
  );
  const view = mount(dialog());
  await waitFor(() => expect(ports.getVersionRecommendations).toHaveBeenCalledTimes(1));
  const signal = vi.mocked(ports.getVersionRecommendations).mock.calls[0][2];
  const nextScope: KnowledgeQueryScope = { ...scope, identityKey: "user8/credential-b", tenantId: 202, managementTenantId: 202 };
  view.update(dialog(nextScope));
  expect(await screen.findByText("New scope candidate")).toBeVisible();
  expect(signal?.aborted).toBe(true);
  await act(async () => { resolve([{ target_document_id: 61, title: "Retired scope candidate", current_primary_version_no: 1, similarity: 0.98 }]); });
  expect(screen.queryByText("Retired scope candidate")).not.toBeInTheDocument();
  view.update(dialog(nextScope), false);
  expect(screen.queryByRole("dialog", { name: "dialog_title" })).not.toBeInTheDocument();
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

it("opens the client's two-column similar dialog directly rather than nesting it in version history", async () => {
  const ports = api();
  mocks.get.mockResolvedValue([{ knowledge_file_id: 12, file_name: "Current.pdf", candidate_count: 0 }]);
  mount(<SpaceVersionHistorySheet scope={scope} spaceId={7} parentId={null} fileId={12} open hasSimilar initialPanel="similar" api={ports} onOpenChange={vi.fn()} />);
  expect(await screen.findByText("section_current_file")).toBeVisible();
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(ports.getSpaceFileVersions).not.toHaveBeenCalled();
});
