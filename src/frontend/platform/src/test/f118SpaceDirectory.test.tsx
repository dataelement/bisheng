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
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Files, { type FilesProps } from "@/pages/KnowledgePage/components/Files";
import type {
  KnowledgeSpaceChild,
  CursorPage,
} from "@/controllers/API/knowledgeSpace";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  children: vi.fn(),
  search: vi.fn(),
  preview: vi.fn(),
  download: vi.fn(),
  permissions: vi.fn(),
  error: vi.fn(),
  legacy: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({
  default: { get: mocks.get, post: mocks.post, put: mocks.put },
  showApiError: mocks.error,
}));
vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: mocks.permissions,
}));
vi.mock("@/controllers/API", () => ({
  readFileByLibDatabase: mocks.legacy,
  getKnowledgeDetailApi: mocks.legacy,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: "en", loadNamespaces: vi.fn() },
  }),
}));
vi.mock("@/pages/KnowledgePage/components/PreviewFile", () => ({
  default: (props: {
    edit: boolean;
    previewData: unknown;
    urlState: { url: string };
  }) => <output data-testid="original-preview">{JSON.stringify(props)}</output>,
}));
const scope: KnowledgeQueryScope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary",
};
const clients: QueryClient[] = [];
let grants: Map<string, string[]>;
const row = (
  id = 11,
  name = "report.pdf",
  file_type = 1,
): KnowledgeSpaceChild => ({
  id,
  knowledge_id: 7,
  file_name: name,
  file_type,
  status: 2,
  parse_type: "uns",
  update_time: "2026-11-07T12:00:00",
});
const page = (
  data: KnowledgeSpaceChild[],
  next_cursor: string | null = null,
): CursorPage<KnowledgeSpaceChild> => ({
  data,
  page_size: 40,
  has_more: next_cursor !== null,
  next_cursor,
});
const permission = (actions: string[] = []) => ({
  actions,
  mode: "INHERIT",
  sources: [],
  roster_complete: true,
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function mount(props: Partial<FilesProps> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  const view = (next: Partial<FilesProps>) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Files onPreview={vi.fn()} scope={scope} spaceId={7} {...next} />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const result = render(view(props));
  return {
    ...result,
    client,
    update: (next: Partial<FilesProps>) => result.rerender(view(next)),
  };
}
const queryRename = () => screen.queryByRole("menuitem", { name: "rename" });
async function menu(name = "report.pdf") {
  const target = await screen.findByLabelText(`more ${name}`);
  fireEvent.keyDown(target, { key: "Enter" });
  return screen.findByRole("menu");
}
async function rename(name = "report.pdf") {
  const target = await menu(name);
  fireEvent.click(
    await within(target).findByRole("menuitem", { name: "rename" }),
  );
  return screen.findByRole("dialog");
}
beforeEach(() => {
  vi.clearAllMocks();
  grants = new Map([["knowledge_space:7", ["visible"]]]);
  mocks.legacy.mockResolvedValue([]);
  mocks.children.mockResolvedValue(page([row()]));
  mocks.search.mockResolvedValue({
    page: 1,
    page_size: 40,
    data: [row(21, "search.pdf")],
    has_more: false,
  });
  mocks.preview.mockResolvedValue({
    original_url: "https://objects.test/original.pdf",
    preview_url: "https://objects.test/preview.pdf",
    file_source: "web_link",
    source_url: "https://source.test",
    final_url: "https://final.test",
    web_title: "Real title",
    media_kind: "",
    html_preview_url: "https://objects.test/page",
  });
  mocks.download.mockResolvedValue({
    original_url: "https://objects.test/download.pdf",
    preview_url: "",
  });
  mocks.permissions.mockImplementation(async (type: string, id: string) =>
    permission(grants.get(`${type}:${id}`)),
  );
  mocks.get.mockImplementation(
    (url: string, options?: { params?: unknown }) => {
      if (url.endsWith("/children")) return mocks.children(options?.params);
      if (url.endsWith("/search")) return mocks.search(options?.params);
      if (url.endsWith("/preview")) return mocks.preview(url);
      if (url.endsWith("/download")) return mocks.download(url);
      throw new Error(`unexpected API read: ${url}`);
    },
  );
  mocks.post.mockResolvedValue(row(31, "Created", 0));
  mocks.put.mockResolvedValue(row(11, "renamed.pdf"));
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
    () => undefined,
  );
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.restoreAllMocks();
});
it("reads real SPACE children and continues an opaque empty page without total", async () => {
  mocks.children
    .mockResolvedValueOnce(page([], "opaque/+=="))
    .mockResolvedValueOnce(page([row()]));
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "f118.more_files" }),
  );
  await screen.findByRole("button", { name: "report.pdf" });
  expect(mocks.children.mock.calls.map((call) => call[0].cursor)).toEqual([
    undefined,
    "opaque/+==",
  ]);
  expect(mocks.get).toHaveBeenCalledWith("/api/v1/knowledge/space/7/children", {
    params: expect.objectContaining({ page_size: 40 }),
  });
  expect(mocks.legacy).not.toHaveBeenCalled();
});
it("keeps search as a real page query and returns to a fresh first directory cursor", async () => {
  mocks.children.mockResolvedValue(page([row()], "directory-next"));
  mocks.search
    .mockResolvedValueOnce({
      page: 1,
      page_size: 40,
      data: [row(21, "search.pdf")],
      has_more: true,
    })
    .mockResolvedValueOnce({
      page: 2,
      page_size: 40,
      data: [row(22, "last.pdf")],
      has_more: false,
    });
  mount();
  await screen.findByText("report.pdf");
  const search = screen.getByPlaceholderText("searchFileName");
  fireEvent.change(search, { target: { value: "policy" } });
  await screen.findByText("search.pdf");
  fireEvent.click(screen.getByRole("button", { name: "pagination.next" }));
  await screen.findByText("last.pdf");
  expect(mocks.search.mock.calls.map((call) => call[0])).toEqual([
    expect.objectContaining({ keyword: "policy", page: 1 }),
    expect.objectContaining({ keyword: "policy", page: 2 }),
  ]);
  expect(
    mocks.search.mock.calls.every(
      (call) => !("cursor" in call[0]) && !("name" in call[0]),
    ),
  ).toBe(true);
  fireEvent.change(search, { target: { value: "" } });
  await screen.findByText("report.pdf");
  expect(mocks.children).toHaveBeenCalledTimes(2);
  expect(mocks.children.mock.lastCall?.[0].cursor).toBeUndefined();
});
it("only loads each row's real namespace actions when its menu opens", async () => {
  grants.set("knowledge_space:7", ["edit", "delete"]);
  grants.set("knowledge_file:11", ["edit"]);
  mocks.children.mockResolvedValue(page([row(), row(9, "Folder", 0)]));
  mount();
  await screen.findByText("report.pdf");
  expect(mocks.permissions.mock.calls).toEqual([["knowledge_space", "7"]]);
  await menu();
  await waitFor(() =>
    expect(mocks.permissions).toHaveBeenCalledWith("knowledge_file", "11"),
  );
  expect(queryRename()).not.toBeInTheDocument();
  expect(
    screen.queryByRole("menuitem", { name: "downloadOriginal" }),
  ).not.toBeInTheDocument();
  await menu("Folder");
  await waitFor(() =>
    expect(mocks.permissions).toHaveBeenCalledWith("folder", "9"),
  );
  expect(
    mocks.permissions.mock.calls.some(
      (call) => call[0] === "knowledge_library",
    ),
  ).toBe(false);
});
it("previews visible-only files through preview without download, Chunk, or file-share", async () => {
  mocks.children.mockResolvedValue(page([{ ...row(), status: 3 }]));
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "report.pdf" }));
  const preview = await screen.findByTestId("original-preview");
  expect(JSON.parse(preview.textContent ?? "{}")).toMatchObject({
    edit: false,
    previewData: {
      file_source: "web_link",
      html_preview_url: "https://objects.test/page",
    },
  });
  expect(mocks.preview).toHaveBeenCalledExactlyOnceWith(
    "/api/v1/knowledge/space/7/files/11/preview",
  );
  expect(mocks.download).not.toHaveBeenCalled();
  expect(mocks.permissions).not.toHaveBeenCalledWith("knowledge_file", "11");
  expect(mocks.legacy).not.toHaveBeenCalled();
});
it("uses target rename independently of root edit or delete", async () => {
  grants.set("knowledge_file:11", ["visible", "rename"]);
  mount();
  await rename();
  fireEvent.change(screen.getByLabelText("name"), {
    target: { value: "renamed.pdf" },
  });
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() =>
    expect(mocks.put).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/knowledge/space/7/files/11",
      { name: "renamed.pdf" },
    ),
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(mocks.children).toHaveBeenCalledTimes(2);
  expect(
    screen.queryByRole("menuitem", { name: "delete" }),
  ).not.toBeInTheDocument();
});
it("downloads only after an explicit download action and keeps preview separate", async () => {
  grants.set("knowledge_file:11", ["download"]);
  mount();
  fireEvent.click(
    await within(await menu()).findByRole("menuitem", {
      name: "downloadOriginal",
    }),
  );
  await waitFor(() =>
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce(),
  );
  const anchor = vi.mocked(HTMLAnchorElement.prototype.click).mock
    .contexts[0] as HTMLAnchorElement;
  expect(anchor.href).toBe("https://objects.test/download.pdf");
  expect(anchor.download).toBe("report.pdf");
  expect(mocks.preview).not.toHaveBeenCalled();
});
it.each([null, 9])(
  "checks create_folder on the actual current container %s",
  async (parentId) => {
    grants.set(parentId === null ? "knowledge_space:7" : "folder:9", [
      "create_folder",
    ]);
    mount({ parentId });
    fireEvent.click(
      await screen.findByRole("button", { name: "f118.create_folder" }),
    );
    fireEvent.change(screen.getByLabelText("f118.folder_name"), {
      target: { value: "Created" },
    });
    fireEvent.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledExactlyOnceWith(
        "/api/v1/knowledge/space/7/folders",
        {
          name: "Created",
          ...(parentId === null ? {} : { parent_id: parentId }),
        },
      ),
    );
    expect(mocks.permissions).toHaveBeenCalledWith(
      parentId === null ? "knowledge_space" : "folder",
      String(parentId ?? 7),
    );
    if (parentId !== null)
      expect(mocks.permissions).not.toHaveBeenCalledWith(
        "knowledge_space",
        "7",
      );
  },
);
it("uses folder rename, not file rename, and sends only the actual name", async () => {
  mocks.children.mockResolvedValue(page([row(9, "Folder", 0)]));
  grants.set("folder:9", ["rename", "download"]);
  mount();
  await rename("Folder");
  fireEvent.change(screen.getByLabelText("name"), {
    target: { value: "Renamed folder" },
  });
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() =>
    expect(mocks.put).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/knowledge/space/7/folders/9",
      { name: "Renamed folder" },
    ),
  );
  expect(mocks.download).not.toHaveBeenCalled();
});
it.each(["scope", "parent"])(
  "retires delayed permission results across %s ABA",
  async (change) => {
    const old = deferred<ReturnType<typeof permission>>();
    mocks.permissions.mockImplementation((type: string) =>
      type === "knowledge_file" ? old.promise : Promise.resolve(permission()),
    );
    const view = mount();
    await menu();
    view.update(
      change === "scope"
        ? { scope: { ...scope, tenantId: 202, managementTenantId: 202 } }
        : { parentId: 9 },
    );
    await screen.findByText("report.pdf");
    view.update({});
    await screen.findByText("report.pdf");
    await act(async () => old.resolve(permission(["rename", "download"])));
    expect(queryRename()).not.toBeInTheDocument();
    expect(mocks.put).not.toHaveBeenCalled();
  },
);
it("retires consumed directory cursors and delayed search rows across search ABA", async () => {
  const old = deferred<{
    page: number;
    page_size: number;
    data: KnowledgeSpaceChild[];
    has_more: boolean;
  }>();
  mocks.search.mockReturnValueOnce(old.promise).mockResolvedValue({
    page: 1,
    page_size: 40,
    data: [row(22, "new.pdf")],
    has_more: false,
  });
  mount();
  const input = await screen.findByPlaceholderText("searchFileName");
  fireEvent.change(input, { target: { value: "policy" } });
  await waitFor(() => expect(mocks.search).toHaveBeenCalledTimes(1));
  fireEvent.change(input, { target: { value: "" } });
  await screen.findByText("report.pdf");
  fireEvent.change(input, { target: { value: "policy" } });
  await screen.findByText("new.pdf");
  await act(async () =>
    old.resolve({
      page: 1,
      page_size: 40,
      data: [row(23, "obsolete.pdf")],
      has_more: false,
    }),
  );
  expect(screen.queryByText("obsolete.pdf")).not.toBeInTheDocument();
  expect(mocks.search).toHaveBeenCalledTimes(2);
});
it("resets opaque paging when a status filter is applied and does not resurrect old pages", async () => {
  mocks.children.mockResolvedValue(page([row()], "next"));
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "f118.more_files" }),
  );
  await waitFor(() => expect(mocks.children).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByRole("button", { name: "status" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "parseFailed" }));
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await waitFor(() =>
    expect(mocks.children.mock.lastCall?.[0]).toMatchObject({
      file_status: [3],
    }),
  );
  expect(mocks.children.mock.lastCall?.[0].cursor).toBeUndefined();
});
it("ignores an old preview after closing and opening a different original file", async () => {
  const old = deferred<unknown>();
  mocks.children.mockResolvedValue(page([row(), row(12, "second.pdf")]));
  mocks.preview.mockReturnValueOnce(old.promise).mockResolvedValue({
    original_url: "https://objects.test/new.pdf",
    preview_url: "",
    file_source: null,
  });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "report.pdf" }));
  fireEvent.click(screen.getByRole("button", { name: "cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "second.pdf" }));
  await screen.findByTestId("original-preview");
  await act(async () =>
    old.resolve({
      original_url: "https://objects.test/old.pdf",
      preview_url: "",
    }),
  );
  expect(screen.getByTestId("original-preview").textContent).toContain(
    "new.pdf",
  );
  expect(screen.getByTestId("original-preview").textContent).not.toContain(
    "old.pdf",
  );
});
it("ignores a delayed download after a tenant change", async () => {
  const old = deferred<unknown>();
  mocks.download.mockReturnValue(old.promise);
  grants.set("knowledge_file:11", ["download"]);
  const view = mount();
  fireEvent.click(
    await within(await menu()).findByRole("menuitem", {
      name: "downloadOriginal",
    }),
  );
  await waitFor(() => expect(mocks.download).toHaveBeenCalledOnce());
  view.update({ scope: { ...scope, tenantId: 202, managementTenantId: 202 } });
  await act(async () =>
    old.resolve({
      original_url: "https://objects.test/old.pdf",
      preview_url: "",
    }),
  );
  expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
});
it("keeps failed rename open and reports the original API error", async () => {
  const error = { status_code: 18023, data: { original: true } };
  mocks.put.mockRejectedValue(error);
  grants.set("knowledge_file:11", ["rename"]);
  mount();
  await rename();
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(mocks.error).toHaveBeenCalledWith(error));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(screen.getByLabelText("name")).toHaveValue("report.pdf");
});
it("does not close a new rename dialog when an older save completes", async () => {
  const old = deferred<unknown>();
  mocks.put.mockReturnValueOnce(old.promise);
  mocks.children.mockResolvedValue(page([row(), row(12, "second.pdf")]));
  grants.set("knowledge_file:11", ["rename"]);
  grants.set("knowledge_file:12", ["rename"]);
  mount();
  await rename();
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  fireEvent.click(screen.getByRole("button", { name: "cancel" }));
  await rename("second.pdf");
  await act(async () => old.resolve(row()));
  expect(screen.getByLabelText("name")).toHaveValue("second.pdf");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(mocks.children).toHaveBeenCalledTimes(1);
});
it("rechecks the dialog epoch after awaiting cache invalidation", async () => {
  const old = deferred<void>();
  grants.set("knowledge_file:11", ["rename"]);
  const view = mount();
  const invalidation = vi
    .spyOn(view.client, "invalidateQueries")
    .mockReturnValueOnce(old.promise);
  await rename();
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(invalidation).toHaveBeenCalledOnce());
  fireEvent.click(screen.getByRole("button", { name: "cancel" }));
  await rename();
  fireEvent.change(screen.getByLabelText("name"), {
    target: { value: "new-draft.pdf" },
  });
  await act(async () => old.resolve());
  expect(screen.getByLabelText("name")).toHaveValue("new-draft.pdf");
});
it("retires a pending preview error on unmount and fails closed without a trusted scope", async () => {
  const old = deferred<unknown>();
  mocks.preview.mockReturnValue(old.promise);
  const view = mount();
  fireEvent.click(await screen.findByRole("button", { name: "report.pdf" }));
  view.unmount();
  await act(async () => old.reject({ status_code: 19000 }));
  expect(mocks.error).not.toHaveBeenCalled();
  mocks.get.mockClear();
  mocks.permissions.mockClear();
  mount({ scope: undefined });
  expect(mocks.get).not.toHaveBeenCalled();
  expect(mocks.permissions).not.toHaveBeenCalled();
});
it("retires a rename draft permanently when its row disappears before returning", async () => {
  grants.set("knowledge_file:11", ["rename"]);
  const view = mount();
  await rename();
  fireEvent.change(screen.getByLabelText("name"), {
    target: { value: "stale-draft.pdf" },
  });
  mocks.children.mockResolvedValue(page([]));
  await act(() => view.client.invalidateQueries());
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  grants.set("knowledge_file:11", ["visible"]);
  mocks.children.mockResolvedValue(page([row(11, "restored.pdf")]));
  await act(() => view.client.invalidateQueries());
  await screen.findByText("restored.pdf");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(mocks.put).not.toHaveBeenCalled();
});
it("ignores a pending grant after refreshed row removal and restoration", async () => {
  const pending = deferred<ReturnType<typeof permission>>();
  mocks.permissions.mockImplementation((type: string) =>
    type === "knowledge_file" ? pending.promise : Promise.resolve(permission()),
  );
  const view = mount();
  await menu();
  mocks.children.mockResolvedValue(page([]));
  await act(() => view.client.invalidateQueries());
  await waitFor(() =>
    expect(screen.queryByLabelText("more report.pdf")).not.toBeInTheDocument(),
  );
  mocks.children.mockResolvedValue(page([row(11, "restored.pdf")]));
  await act(() => view.client.invalidateQueries());
  await screen.findByText("restored.pdf");
  await act(async () => pending.resolve(permission(["rename"])));
  expect(queryRename()).not.toBeInTheDocument();
});
it("presents the successful actions after retrying a failed permission lookup", async () => {
  const pending = deferred<ReturnType<typeof permission>>();
  let calls = 0;
  mocks.permissions.mockImplementation((type: string) => {
    if (type !== "knowledge_file") return Promise.resolve(permission());
    return ++calls === 1
      ? Promise.reject({ status_code: 25011 })
      : pending.promise;
  });
  mount();
  const target = await menu();
  fireEvent.click(
    await within(target).findByRole("menuitem", { name: "retry" }),
  );
  await waitFor(() => expect(calls).toBe(2));
  await act(async () => pending.resolve(permission(["rename"])));
  expect(
    await screen.findByRole("menuitem", { name: "rename" }),
  ).toBeInTheDocument();
});
