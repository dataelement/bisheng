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
import { SpaceSimilarDocumentDialog } from "@/pages/KnowledgePage/components/SpaceSimilarDocumentDialog";
import { SpaceDirectoryRow } from "@/pages/KnowledgePage/components/SpaceDirectoryRow";
import type {
  KnowledgeVersionsApi,
  SpaceVersionHistory,
} from "@/controllers/API/knowledgeVersions";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  error: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({
  default: { get: mocks.get, post: mocks.post },
  showApiError: mocks.error,
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
  const confirmation = await screen.findByRole("alertdialog");
  await act(async () => {
    fireEvent.click(within(confirmation).getByRole("button", { name: "confirm" }));
  });
}
beforeEach(() => {
  vi.resetAllMocks();
  mocks.get.mockResolvedValue({ actions: ["visible", "edit", "upload_file", "delete"] });
  mocks.post.mockResolvedValue({ check_complete: true, valid_items: [] });
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
  for (const name of ["history.actions.primary", "history.actions.delete"]) {
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  }
  expect(ports.deleteSpaceFileVersion).not.toHaveBeenCalled();
  expect(ports.setSpacePrimaryVersion).not.toHaveBeenCalled();
});

it("checks delete on the historical physical file requiring file edit as well", async () => {
  mocks.get.mockImplementation(async (url: string) => ({ actions:
    url.includes("knowledge_file/11/") ? ["visible", "edit"] : ["visible"],
  }));
  const ports = api();
  mount(<SpaceVersionHistorySheet scope={scope} spaceId={7} parentId={9} fileId={12} open onOpenChange={vi.fn()} api={ports} />);
  expect(await screen.findByRole("button", { name: "history.actions.primary" })).toBeVisible();
  await waitFor(() => expect(mocks.get).toHaveBeenCalledWith(expect.stringContaining("knowledge_file/11/my-permissions"), { signal: expect.any(AbortSignal) }));
  expect(screen.queryByRole("button", { name: "history.actions.delete" })).not.toBeInTheDocument();
});

it("ignores late history mutation grants from a retired tenant view", async () => {
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
  for (const name of ["history.actions.primary", "history.actions.delete"]) {
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  }
});

it("opens version management for a parsed single-version file only with file edit and the feature flag", async () => {
  mocks.get.mockImplementation(async (url: string) => url.endsWith("/my-permissions") ? { actions: ["edit", "upload_file"] } : []);
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
    await screen.findByRole("menuitem", { name: "knowledge.version.dialog_title" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "dialog_title" });
  expect(dialog).toHaveClass("left-1/2", "top-1/2", "max-w-[min(720px,90vw)]");
  expect(within(dialog).getByRole("button", { name: "btn_dismiss" })).toBeVisible();
  expect(within(dialog).getByRole("textbox", { name: "search_placeholder" })).toBeVisible();
  expect(within(dialog).queryByRole("button", { name: "versions.new_version" })).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog", { name: "history.title" })).not.toBeInTheDocument();
  view.update(row, false);
  await waitFor(() =>
    expect(
      screen.queryByRole("dialog", { name: "dialog_title" }),
    ).not.toBeInTheDocument(),
  );
  expect(
    screen.queryByRole("menuitem", { name: "knowledge.version.dialog_title" }),
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
    await screen.findByRole("button", { name: "history.actions.primary" }),
  );
  expect(ports.setSpacePrimaryVersion).not.toHaveBeenCalled();
  await confirmLast();
  await waitFor(() => expect(ports.setSpacePrimaryVersion).toHaveBeenCalledExactlyOnceWith(51, expect.any(AbortSignal)));
  await waitFor(() =>
    expect(ports.getSpaceFileVersions).toHaveBeenCalledTimes(2),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "history.actions.delete" }),
  );
  await confirmLast();
  await waitFor(() => expect(ports.deleteSpaceFileVersion).toHaveBeenCalledExactlyOnceWith(51, expect.any(AbortSignal)));
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
  expect(screen.queryByRole("button", { name: "history.actions.primary" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "history.actions.delete" })).not.toBeInTheDocument();
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
    await screen.findByRole("button", { name: "history.actions.delete" }),
  );
  await confirmLast();
  expect(await screen.findByText("history.uncertain")).toBeVisible();
  const deleteButton = screen.getByRole("button", { name: "history.actions.delete" });
  expect(deleteButton).toBeDisabled();
  expect(ports.deleteSpaceFileVersion).toHaveBeenCalledTimes(1);
  expect(mocks.error).toHaveBeenCalledWith(error);
  fireEvent.click(deleteButton);
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(ports.deleteSpaceFileVersion).toHaveBeenCalledTimes(1);
  view.update(
    <SpaceVersionHistorySheet
      {...props}
      scope={{ ...scope, identityKey: "user8/credential-b" }}
    />,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "history.actions.primary" }),
  );
  expect(await screen.findByRole("alertdialog")).toBeVisible();
  view.update(<SpaceVersionHistorySheet {...props} />, false);
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(ports.setSpacePrimaryVersion).not.toHaveBeenCalled();
});

it("aborts a confirmed history write when the active tenant scope changes", async () => {
  const ports = api();
  let finish!: (result: Awaited<ReturnType<KnowledgeVersionsApi["setSpacePrimaryVersion"]>>) => void;
  vi.mocked(ports.setSpacePrimaryVersion).mockReturnValue(
    new Promise((resolve) => { finish = resolve; }),
  );
  const props = { spaceId: 7, parentId: null, fileId: 12, open: true, onOpenChange: vi.fn(), api: ports };
  const view = mount(<SpaceVersionHistorySheet {...props} scope={scope} />);
  fireEvent.click(await screen.findByRole("button", { name: "history.actions.primary" }));
  await confirmLast();
  await waitFor(() => expect(ports.setSpacePrimaryVersion).toHaveBeenCalledExactlyOnceWith(51, expect.any(AbortSignal)));
  expect(screen.getByRole("button", { name: "btn_close" })).toBeDisabled();
  const signal = vi.mocked(ports.setSpacePrimaryVersion).mock.calls[0][1];
  const nextScope = { ...scope, identityKey: "user8/credential-b", tenantId: 202, managementTenantId: 202 };
  view.update(<SpaceVersionHistorySheet {...props} scope={nextScope} />);
  expect(signal?.aborted).toBe(true);
  await act(async () => finish({ document_id: 41, new_primary_version_no: 1 }));
  await waitFor(() => expect(ports.getSpaceFileVersions).toHaveBeenCalledTimes(2));
  expect(ports.setSpacePrimaryVersion).toHaveBeenCalledTimes(1);
});

it("gathers cursor search pages in the shared management dialog and merges a searched source", async () => {
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
  mount(
    <SpaceSimilarDocumentDialog
      scope={scope}
      spaceId={7}
      fileId={12}
      file={{ id: 12, name: "primary.md" }}
      api={ports}
      onOpenChange={vi.fn()}
      onChanged={onChanged}
    />,
  );
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "Candidate" },
  });
  fireEvent.click(screen.getByRole("button", { name: "search_button" }));
  await screen.findByText("Candidate");
  expect(ports.searchVersionDocuments).toHaveBeenCalledWith(
    7,
    12,
    "Candidate",
    true,
    undefined,
    expect.any(AbortSignal),
  );
  await screen.findByText("Next candidate");
  expect(ports.searchVersionDocuments).toHaveBeenLastCalledWith(
    7,
    12,
    "Candidate",
    true,
    "page2",
    expect.any(AbortSignal),
  );
  fireEvent.click(screen.getAllByRole("button", { name: "btn_link_as_new_version" })[1]);
  await confirmLast();
  await waitFor(() => expect(ports.mergeSpaceFileVersion).toHaveBeenCalledExactlyOnceWith(12, 62, expect.any(AbortSignal)));
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

it("opens the client's two-column similar dialog directly rather than nesting it in version history", async () => {
  const ports = api();
  mocks.get.mockResolvedValue([{ knowledge_file_id: 12, file_name: "Current.pdf", candidate_count: 0 }]);
  mount(<SpaceSimilarDocumentDialog scope={scope} spaceId={7} restrictToFileIds={[12]} api={ports} onOpenChange={vi.fn()} />);
  expect(await screen.findByText("section_current_file")).toBeVisible();
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(ports.getSpaceFileVersions).not.toHaveBeenCalled();
});


it("hides history writes when only the space is editable", async () => {
  mocks.get.mockImplementation(async (url: string) => ({ actions:
    url.includes("knowledge_space/") ? ["visible", "edit", "delete"] : ["visible", "delete"],
  }));
  mount(<SpaceVersionHistorySheet scope={scope} spaceId={7} parentId={9} fileId={12} open onOpenChange={vi.fn()} api={api()} />);
  await screen.findByText("old.md");
  await waitFor(() => expect(mocks.get).toHaveBeenCalledWith(expect.stringContaining("knowledge_file/11/my-permissions"), { signal: expect.any(AbortSignal) }));
  expect(screen.queryByRole("button", { name: "history.actions.primary" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "history.actions.delete" })).not.toBeInTheDocument();
});
