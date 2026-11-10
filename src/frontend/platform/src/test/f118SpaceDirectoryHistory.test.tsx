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
import { useContext, type ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Files, { type FilesProps } from "@/pages/KnowledgePage/components/Files";
import { locationContext } from "@/contexts/locationContext";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import type { SpaceVersionHistory } from "@/controllers/API/knowledgeVersions";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  children: vi.fn(),
  history: vi.fn(),
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
vi.mock("@/pages/KnowledgePage/components/PreviewFile", () => ({
  default: () => <output>original-preview</output>,
}));

const scope: KnowledgeQueryScope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary",
};
const row = (
  props: Partial<KnowledgeSpaceChild> = {},
): KnowledgeSpaceChild => ({
  id: 11,
  knowledge_id: 7,
  file_name: "report.md",
  file_type: 1,
  is_multi_version: true,
  status: 3,
  parse_type: "uns",
  ...props,
});
const page = (data: KnowledgeSpaceChild[]) => ({
  data,
  has_more: false,
  next_cursor: null,
  page_size: 40,
});
const history = (title = "Server visible title"): SpaceVersionHistory => ({
  document_id: 41,
  knowledge_id: 7,
  title,
  doc_code: null,
  current_primary_version_no: null,
  versions: [
    {
      version_id: 51,
      version_no: 3,
      is_primary: false,
      knowledge_file_id: 11,
      original_file_name: "visible-original.md",
      file_code: null,
      uploader_name: null,
      uploader_id: null,
      upload_time: null,
      status: null,
    },
  ],
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}
function Environment({
  enabled,
  children,
}: {
  enabled?: unknown;
  children: ReactNode;
}) {
  const defaults = useContext(locationContext);
  return (
    <locationContext.Provider
      value={{ ...defaults, appConfig: { versionManagementEnabled: enabled } }}
    >
      {children}
    </locationContext.Provider>
  );
}
const clients: QueryClient[] = [];
interface Options {
  enabled?: unknown;
  props?: Partial<FilesProps>;
}
function mount({ enabled = true, props = {} }: Options = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
  });
  clients.push(client);
  const state = { enabled, props };
  const view = () => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Environment enabled={state.enabled}>
          <Files scope={scope} spaceId={7} parentId={9} {...state.props} />
        </Environment>
      </MemoryRouter>
    </QueryClientProvider>
  );
  const result = render(view());
  return {
    ...result,
    client,
    update: (next: Options) => {
      Object.assign(state, next);
      result.rerender(view());
    },
  };
}
async function menu() {
  fireEvent.keyDown(await screen.findByLabelText("more report.md"), {
    key: "Enter",
  });
  return screen.findByRole("menu");
}
async function openHistory() {
  const opened = await menu();
  fireEvent.click(
    await within(opened).findByRole("menuitem", {
      name: "f118.version_history",
    }),
  );
  return screen.findByRole("dialog");
}
let actions: string[];
beforeEach(() => {
  vi.clearAllMocks();
  actions = ["visible"];
  mocks.children.mockResolvedValue(page([row()]));
  mocks.history.mockResolvedValue(history());
  mocks.permissions.mockImplementation(async (type: string) => ({
    actions: type === "knowledge_file" ? actions : [],
    mode: "INHERIT",
    sources: [],
    roster_complete: true,
  }));
  mocks.get.mockImplementation(
    (url: string, options?: { signal?: AbortSignal }) => {
      if (url.endsWith("/children")) return mocks.children();
      if (url.endsWith("/versions")) return mocks.history(url, options?.signal);
      throw new Error(`Unexpected API read: ${url}`);
    },
  );
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});

it.each([false, "true", null])(
  "does not offer history while the feature flag is not true: %s",
  async (enabled) => {
    mount({ enabled });
    const opened = await menu();
    await waitFor(() =>
      expect(mocks.permissions).toHaveBeenCalledWith("knowledge_file", "11"),
    );
    expect(
      within(opened).queryByRole("menuitem", { name: "f118.version_history" }),
    ).not.toBeInTheDocument();
    expect(mocks.history).not.toHaveBeenCalled();
  },
);

it.each([{ is_multi_version: false }, { file_type: 0 }])(
  "retains the original multiversion/nonfolder gate: %s",
  async (override) => {
    mocks.children.mockResolvedValue(page([row(override)]));
    mount();
    const opened = await menu();
    await waitFor(() => expect(mocks.permissions).toHaveBeenCalledTimes(2));
    expect(
      within(opened).queryByRole("menuitem", { name: "f118.version_history" }),
    ).not.toBeInTheDocument();
    expect(mocks.history).not.toHaveBeenCalled();
  },
);

it("reads history from an actual file row with only child visible, without root/edit/SUCCESS gates", async () => {
  mount({ props: { canEditKb: false, canDeleteKb: false } });
  const opened = await openHistory();
  expect(await within(opened).findByText("Server visible title")).toBeVisible();
  expect(within(opened).getByText("visible-original.md")).toBeVisible();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(mocks.history).toHaveBeenCalledExactlyOnceWith(
    "/api/v1/knowledge/space/file/11/versions",
    expect.any(AbortSignal),
  );
  expect(mocks.get.mock.calls.map(([url]) => url)).toEqual([
    "/api/v1/knowledge/space/7/children",
    "/api/v1/knowledge/space/file/11/versions",
  ]);
  expect(mocks.post).not.toHaveBeenCalled();
  expect(mocks.put).not.toHaveBeenCalled();
  expect(mocks.legacy).not.toHaveBeenCalled();
  expect(
    within(opened).queryByText("f118.primary_version"),
  ).not.toBeInTheDocument();
});

it("preserves rename/download actions without offering history when file.visible is absent", async () => {
  actions = ["rename", "download"];
  mount();
  const opened = await menu();
  expect(
    await within(opened).findByRole("menuitem", { name: "rename" }),
  ).toBeVisible();
  expect(
    within(opened).getByRole("menuitem", { name: "downloadOriginal" }),
  ).toBeVisible();
  expect(
    within(opened).queryByRole("menuitem", { name: "f118.version_history" }),
  ).not.toBeInTheDocument();
  expect(mocks.history).not.toHaveBeenCalled();
});

it("waits for the actual lazy permissions response before offering history", async () => {
  const permission = deferred<{
    actions: string[];
    mode: string;
    sources: never[];
    roster_complete: boolean;
  }>();
  mocks.permissions.mockImplementation((type: string) =>
    type === "knowledge_file"
      ? permission.promise
      : Promise.resolve({ actions: [] }),
  );
  mount();
  const opened = await menu();
  expect(
    within(opened).queryByRole("menuitem", { name: "f118.version_history" }),
  ).not.toBeInTheDocument();
  await act(async () =>
    permission.resolve({
      actions: ["visible"],
      mode: "CUSTOM",
      sources: [],
      roster_complete: true,
    }),
  );
  expect(
    await within(opened).findByRole("menuitem", {
      name: "f118.version_history",
    }),
  ).toBeVisible();
  expect(mocks.history).not.toHaveBeenCalled();
});

it("permanently retires an opening when the flag turns off and back on", async () => {
  const old = deferred<SpaceVersionHistory>();
  mocks.history
    .mockReturnValueOnce(old.promise)
    .mockResolvedValue(history("Fresh title"));
  const view = mount();
  await openHistory();
  const signal: AbortSignal = mocks.history.mock.calls[0][1];
  view.update({ enabled: false });
  expect(signal.aborted).toBe(true);
  view.update({ enabled: true });
  await act(async () => old.resolve(history("Retired flag secret")));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(mocks.history).toHaveBeenCalledTimes(1);
  await openHistory();
  expect(await screen.findByText("Fresh title")).toBeVisible();
});

it("does not revive history after a real row disappears and the same file returns", async () => {
  const old = deferred<SpaceVersionHistory>();
  mocks.history
    .mockReturnValueOnce(old.promise)
    .mockResolvedValue(history("New row title"));
  const view = mount();
  await openHistory();
  const signal: AbortSignal = mocks.history.mock.calls[0][1];
  mocks.children.mockResolvedValue(page([]));
  await act(() =>
    view.client.invalidateQueries({
      predicate: (query) => query.queryKey.includes("children"),
    }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(signal.aborted).toBe(true);
  mocks.children.mockResolvedValue(page([row()]));
  await act(() =>
    view.client.invalidateQueries({
      predicate: (query) => query.queryKey.includes("children"),
    }),
  );
  await screen.findByLabelText("more report.md");
  await act(async () => old.resolve(history("Retired row secret")));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await openHistory();
  expect(await screen.findByText("New row title")).toBeVisible();
});

it.each(["scope", "parent"] as const)(
  "retires actual row history on %s ABA",
  async (field) => {
    const old = deferred<SpaceVersionHistory>();
    mocks.history
      .mockReturnValueOnce(old.promise)
      .mockResolvedValue(history("New target title"));
    const view = mount();
    await openHistory();
    const signal: AbortSignal = mocks.history.mock.calls[0][1];
    view.update({
      props:
        field === "scope"
          ? { scope: { ...scope, tenantId: 202, managementTenantId: 202 } }
          : { parentId: 10 },
    });
    await screen.findByLabelText("more report.md");
    view.update({ props: {} });
    await screen.findByLabelText("more report.md");
    await act(async () => old.resolve(history("Old target secret")));
    expect(signal.aborted).toBe(true);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mocks.history).toHaveBeenCalledTimes(1);
    await openHistory();
    expect(await screen.findByText("New target title")).toBeVisible();
  },
);

it("retires history if a refreshed file stops being multiversion", async () => {
  const view = mount();
  await openHistory();
  await screen.findByText("Server visible title");
  mocks.children.mockResolvedValue(page([row({ is_multi_version: false })]));
  await act(() =>
    view.client.invalidateQueries({
      predicate: (query) => query.queryKey.includes("children"),
    }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  mocks.children.mockResolvedValue(page([row()]));
  await act(() =>
    view.client.invalidateQueries({
      predicate: (query) => query.queryKey.includes("children"),
    }),
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
