import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { userContext } from "@/contexts/userContext";
import type { User } from "@/types/api/user";
import FilesUpload from "@/pages/KnowledgePage/filesUpload";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  permission: vi.fn(),
  legacy: vi.fn(),
  error: vi.fn(),
  management: vi.fn(),
  children: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({
  default: { get: mocks.get, post: mocks.post },
  showApiError: mocks.error,
}));
vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: mocks.permission,
  checkResourceActionApi: mocks.legacy,
}));
vi.mock("@/controllers/API", () => ({
  subUploadLibFile: mocks.legacy,
  retryKnowledgeFileApi: mocks.legacy,
}));
vi.mock("@/hooks/useAdminScope", () => ({ useAdminScope: mocks.management }));
vi.mock("@/contexts/userContext", async () => ({
  userContext: (await import("react")).createContext({ user: null }),
}));
vi.mock("@/contexts/locationContext", async () => ({
  locationContext: (await import("react")).createContext({
    appConfig: {
      enableEtl4lm: true,
      enableMediaUpload: false,
      uploadFileMaxSize: 50,
      uploadMediaMaxSize: 1024,
    },
  }),
}));
vi.mock("@/pages/KnowledgePage/components/FileUploadStep1", () => ({
  default: () => null,
}));
vi.mock("@/pages/KnowledgePage/components/FileUploadStep2", () => ({
  default: () => null,
}));
vi.mock("@/pages/KnowledgePage/components/FileUploadStep4", () => ({
  default: () => null,
}));
vi.mock("@/pages/KnowledgePage/components/PreviewResult", () => ({
  default: () => null,
}));

let user: Partial<User>;
let management: {
  scope: { scope_tenant_id: number | null; expires_at: null };
  loading: boolean;
  refresh: ReturnType<typeof vi.fn>;
};
const clients: QueryClient[] = [];
const file = (name = "report.md") =>
  new File(["content"], name, { type: "text/markdown" });
const row = (id = 81, status = 5, file_name = "report.md") => ({
  id,
  knowledge_id: 7,
  file_name,
  file_type: 1,
  status,
});
const page = (data = [row(81, 2)], next_cursor: string | null = null) => ({
  data,
  page_size: 100,
  has_more: next_cursor !== null,
  next_cursor,
});
const permission = (actions = ["upload_file"]) => ({
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
function mount(
  path = "/filelib/upload/7?parent_id=9&fileStatus=abnormal&keep=1",
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  let navigate!: ReturnType<typeof useNavigate>;
  function Navigation() {
    navigate = useNavigate();
    const location = useLocation();
    return (
      <output data-testid="location">
        {location.pathname}
        {location.search}
      </output>
    );
  }
  const view = () => (
    <userContext.Provider
      value={{
        user,
        setUser: vi.fn(),
        savedComponents: [],
        addSavedComponent: async () => undefined,
        checkComponentsName: () => false,
        delComponent: vi.fn(),
      }}
    >
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <Navigation />
          <Routes>
            <Route path="/filelib/upload/:id" element={<FilesUpload />} />
            <Route path="/filelib/:id" element={<p>directory</p>} />
            <Route path="/filelib" element={<p>space-list</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </userContext.Provider>
  );
  const result = render(view());
  return {
    ...result,
    client,
    refresh: () => result.rerender(view()),
    go: (next: string) => act(() => navigate(next)),
  };
}
async function select(files = [file()]) {
  await waitFor(() =>
    expect(document.querySelector('input[type="file"]')).not.toBeNull(),
  );
  const input = document.querySelector('input[type="file"]')!;
  await act(async () => fireEvent.change(input, { target: { files } }));
}
const stageCalls = () =>
  mocks.post.mock.calls.filter(([url]) => url === "/api/v1/knowledge/upload/7");
const registerCalls = () =>
  mocks.post.mock.calls.filter(
    ([url]) => url === "/api/v1/knowledge/space/7/files",
  );
beforeEach(() => {
  vi.clearAllMocks();
  user = { user_id: 7, tenant_id: 1, leaf_tenant_id: 101 };
  management = {
    scope: { scope_tenant_id: 202, expires_at: null },
    loading: false,
    refresh: vi.fn().mockResolvedValue(undefined),
  };
  mocks.management.mockImplementation(() => management);
  mocks.legacy.mockResolvedValue({ allowed: false });
  mocks.permission.mockResolvedValue(permission());
  mocks.children.mockResolvedValue(page());
  mocks.get.mockImplementation(
    (url: string, options?: { params?: unknown }) => {
      if (url.endsWith("/children")) return mocks.children(options?.params);
      throw new Error(`unexpected read: ${url}`);
    },
  );
  mocks.post.mockImplementation(async (url: string, body: unknown) => {
    if (url === "/api/v1/knowledge/upload/7") {
      const value = (body as FormData).get("file") as File;
      return {
        file_path: `tmp/${value.name}`,
        file_name: value.name,
        repeat: false,
      };
    }
    if (url === "/api/v1/knowledge/space/7/files") return [row()];
    throw new Error(`unexpected write: ${url}`);
  });
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.restoreAllMocks();
});

it("allows folder-only upload without root info, root visible, space edit or legacy process", async () => {
  mount();
  await select();
  expect(mocks.permission).toHaveBeenCalledExactlyOnceWith("folder", "9");
  await screen.findByText("completed");
  expect(registerCalls()[0][1]).toEqual({
    file_path: ["tmp/report.md"],
    parent_id: 9,
  });
  expect(
    mocks.get.mock.calls.every(([url]) => String(url).endsWith("/children")),
  ).toBe(true);
  expect(mocks.legacy).not.toHaveBeenCalled();
  expect(screen.getByText("f118.upload_registered")).toBeInTheDocument();
});

it("checks the actual SPACE root upload_file action and preserves directory query on return", async () => {
  mount("/filelib/upload/7?fileStatus=abnormal&keep=1");
  await select();
  await waitFor(() => expect(registerCalls()).toHaveLength(1));
  expect(mocks.permission).toHaveBeenCalledExactlyOnceWith(
    "knowledge_space",
    "7",
  );
  expect(registerCalls()[0][1]).toEqual({
    file_path: ["tmp/report.md"],
    parent_id: null,
  });
  fireEvent.click(screen.getByRole("button", { name: "back" }));
  expect(screen.getByTestId("location")).toHaveTextContent(
    "/filelib/7?fileStatus=abnormal&keep=1",
  );
});

it.each([
  "?parent_id=",
  "?parent_id=0",
  "?parent_id=-1",
  "?parent_id=1.5",
  "?parent_id=9&parent_id=9",
  "?parent_id=9007199254740992",
])("rejects invalid explicit parent without requests %s", async (query) => {
  mount(`/filelib/upload/7${query}`);
  await screen.findByText("f118.scope_unavailable");
  expect(mocks.permission).not.toHaveBeenCalled();
  expect(mocks.get).not.toHaveBeenCalled();
  expect(mocks.post).not.toHaveBeenCalled();
});
it("rejects an unsafe route space ID before any upload authority request", async () => {
  mount("/filelib/upload/9007199254740992");
  await screen.findByText("f118.scope_unavailable");
  expect(mocks.permission).not.toHaveBeenCalled();
});
it("does not treat visible or edit as upload_file", async () => {
  mocks.permission.mockResolvedValue(permission(["visible", "edit"]));
  mount();
  await screen.findByText("noOperationPermission");
  expect(document.querySelector('input[type="file"]')).toBeNull();
  expect(mocks.post).not.toHaveBeenCalled();
});
it("keeps unknown permission rejected and lets the actual check retry", async () => {
  const error = { status_code: 19000, data: { original: true } };
  mocks.permission.mockRejectedValueOnce(error).mockResolvedValue(permission());
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "retry" }));
  await select();
  await waitFor(() => expect(registerCalls()).toHaveLength(1));
  expect(mocks.error).toHaveBeenCalledWith(error);
});
it("waits for server-selected management scope and preserves the original actor home", async () => {
  user = { ...user, is_global_super: true };
  management.loading = true;
  const view = mount();
  expect(mocks.permission).not.toHaveBeenCalled();
  management.loading = false;
  view.refresh();
  await select();
  await waitFor(() => expect(registerCalls()).toHaveLength(1));
  expect(user.tenant_id).toBe(1);
});
it("does not report completion after staging before registration finishes", async () => {
  const pending = deferred<ReturnType<typeof row>[]>();
  mocks.post.mockImplementation(async (url: string) =>
    url.endsWith("/files")
      ? pending.promise
      : { file_path: "tmp/a", repeat: false },
  );
  mount();
  await select();
  await screen.findByText("f118.upload_staged");
  expect(screen.queryByText("completed")).not.toBeInTheDocument();
  expect(mocks.children).not.toHaveBeenCalled();
  await act(async () => pending.resolve([row()]));
  await screen.findByText("completed");
});
it("uses registered IDs rather than names/order and follows a sparse progressing status cursor", async () => {
  mocks.post.mockImplementation(async (url: string) =>
    url.endsWith("/files")
      ? [row(92, 3, "same.md"), row(81, 5, "same.md")]
      : { file_path: "tmp/a", repeat: false },
  );
  mocks.children
    .mockResolvedValueOnce(page([], "opaque/+=="))
    .mockResolvedValueOnce(page([row(81, 2, "same.md")]));
  mount();
  await select([file("same.md")]);
  await screen.findByText("completed");
  expect(screen.getByText("parseFailed")).toBeInTheDocument();
  expect(mocks.children.mock.calls.map(([query]) => query)).toEqual([
    { parent_id: 9, file_ids: [81], page_size: 100 },
    { parent_id: 9, file_ids: [81], page_size: 100, cursor: "opaque/+==" },
  ]);
});
it("does not turn omitted status rows into a successful parse", async () => {
  mocks.children.mockResolvedValue(page([]));
  mount();
  await select();
  await screen.findByText("f118.upload_status_unavailable");
  expect(screen.queryByText("completed")).not.toBeInTheDocument();
});
it("retries failed status reads without uploading or registering again", async () => {
  const error = { status_code: 10998, data: { original: true } };
  mocks.children.mockRejectedValueOnce(error).mockResolvedValue(page());
  mount();
  await select();
  fireEvent.click(await screen.findByRole("button", { name: "retry" }));
  await screen.findByText("completed");
  expect(stageCalls()).toHaveLength(1);
  expect(registerCalls()).toHaveLength(1);
  expect(mocks.error).toHaveBeenCalledWith(error);
});
it("reuses the actual staged body after a registration failure and keeps the original error", async () => {
  const error = { status_code: 10999, data: { original: true } };
  let registrations = 0;
  mocks.post.mockImplementation(async (url: string) => {
    if (!url.endsWith("/files")) return { file_path: "tmp/a", repeat: false };
    if (++registrations === 1) throw error;
    return [row()];
  });
  mount();
  await select();
  fireEvent.click(await screen.findByRole("button", { name: "retry" }));
  await screen.findByText("completed");
  expect(stageCalls()).toHaveLength(1);
  expect(registerCalls()).toHaveLength(2);
  expect(mocks.error).toHaveBeenCalledWith(error);
});
it("aborts staging on cancel and never registers a late successful body", async () => {
  const pending = deferred<{ file_path: string; repeat: boolean }>();
  mocks.post.mockReturnValue(pending.promise);
  mount();
  await select();
  await waitFor(() => expect(stageCalls()).toHaveLength(1));
  const signal = stageCalls()[0][2].signal as AbortSignal;
  fireEvent.click(screen.getByRole("button", { name: "cancel" }));
  expect(signal.aborted).toBe(true);
  await act(async () =>
    pending.resolve({ file_path: "tmp/late", repeat: false }),
  );
  expect(registerCalls()).toHaveLength(0);
  expect(screen.getByText("f118.upload_cancelled")).toBeInTheDocument();
});
it("retires a cancelled registration without pretending the server rolled it back", async () => {
  const pending = deferred<ReturnType<typeof row>[]>();
  mocks.post.mockImplementation(async (url: string) =>
    url.endsWith("/files")
      ? pending.promise
      : { file_path: "tmp/a", repeat: false },
  );
  mount();
  await select();
  await waitFor(() => expect(registerCalls()).toHaveLength(1));
  const signal = registerCalls()[0][2].signal as AbortSignal;
  fireEvent.click(screen.getByRole("button", { name: "cancel" }));
  expect(signal.aborted).toBe(true);
  await act(async () => pending.resolve([row()]));
  expect(mocks.children).not.toHaveBeenCalled();
  expect(screen.getByText("f118.upload_may_continue")).toBeInTheDocument();
  expect(screen.queryByText("completed")).not.toBeInTheDocument();
});
it.each(["scope", "parent"])(
  "permanently retires a pending upload across %s A-B-A",
  async (kind) => {
    const pending = deferred<{ file_path: string; repeat: boolean }>();
    mocks.post.mockReturnValue(pending.promise);
    const view = mount();
    await select();
    await waitFor(() => expect(stageCalls()).toHaveLength(1));
    const signal = stageCalls()[0][2].signal as AbortSignal;
    if (kind === "scope") {
      user = { ...user, leaf_tenant_id: 202 };
      view.refresh();
    } else view.go("/filelib/upload/7?parent_id=10");
    await waitFor(() => expect(signal.aborted).toBe(true));
    if (kind === "scope") {
      user = { ...user, leaf_tenant_id: 101 };
      view.refresh();
    } else view.go("/filelib/upload/7?parent_id=9");
    await act(async () =>
      pending.resolve({ file_path: "tmp/old", repeat: false }),
    );
    expect(registerCalls()).toHaveLength(0);
    expect(screen.queryByText("report.md")).not.toBeInTheDocument();
  },
);
it("aborts pending staging on full unmount", async () => {
  const pending = deferred<{ file_path: string; repeat: boolean }>();
  mocks.post.mockReturnValue(pending.promise);
  const view = mount();
  await select();
  await waitFor(() => expect(stageCalls()).toHaveLength(1));
  const signal = stageCalls()[0][2].signal as AbortSignal;
  view.unmount();
  expect(signal.aborted).toBe(true);
  await act(async () =>
    pending.resolve({ file_path: "tmp/late", repeat: false }),
  );
  expect(registerCalls()).toHaveLength(0);
});
it("does not upload oversized files accepted by the shared format-only DropZone", async () => {
  const huge = file();
  Object.defineProperty(huge, "size", { value: 51 * 1024 * 1024 });
  mount();
  await select([huge]);
  expect(mocks.post).not.toHaveBeenCalled();
});
it("never exposes cancellation as deletion after registration has completed", async () => {
  mount();
  await select();
  await screen.findByText("completed");
  expect(
    screen.queryByRole("button", { name: "cancel" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("f118.upload_may_continue")).toBeInTheDocument();
});

it("bounds exact status IDs to batches of 100 rather than scanning the whole directory", async () => {
  const registered = Array.from({ length: 101 }, (_, index) => row(index + 1));
  mocks.post.mockImplementation(async (url: string) =>
    url.endsWith("/files") ? registered : { file_path: "tmp/a", repeat: false },
  );
  mocks.children.mockImplementation(async (query: { file_ids: number[] }) =>
    page(query.file_ids.map((id) => row(id, 2))),
  );
  mount();
  await select();
  await waitFor(() =>
    expect(screen.getAllByText("completed")).toHaveLength(101),
  );
  expect(
    mocks.children.mock.calls.map(([query]) => query.file_ids.length),
  ).toEqual([100, 1]);
  expect(
    mocks.children.mock.calls.flatMap(([query]) => query.file_ids),
  ).toEqual(registered.map(({ id }) => id));
});
it("fails a nonprogressing status cursor instead of inventing completion or looping", async () => {
  mocks.children.mockResolvedValue(page([], "same-cursor"));
  mount();
  await select();
  await screen.findByText("f118.upload_status_unavailable");
  expect(mocks.children).toHaveBeenCalledTimes(2);
  expect(screen.queryByText("completed")).not.toBeInTheDocument();
});
it("keeps an old cancelled attempt retired after the same item is retried", async () => {
  const old = deferred<{ file_path: string; repeat: boolean }>();
  const fresh = deferred<{ file_path: string; repeat: boolean }>();
  let stages = 0;
  mocks.post.mockImplementation(async (url: string) =>
    url.endsWith("/files")
      ? [row()]
      : ++stages === 1
        ? old.promise
        : fresh.promise,
  );
  mount();
  await select();
  await waitFor(() => expect(stageCalls()).toHaveLength(1));
  fireEvent.click(screen.getByRole("button", { name: "cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await waitFor(() => expect(stageCalls()).toHaveLength(2));
  await act(async () => old.resolve({ file_path: "tmp/old", repeat: false }));
  expect(registerCalls()).toHaveLength(0);
  await act(async () =>
    fresh.resolve({ file_path: "tmp/fresh", repeat: false }),
  );
  await screen.findByText("completed");
  expect(registerCalls()[0][1].file_path).toEqual(["tmp/fresh"]);
});
it("retires late permission results through scope A-B-A without mounting an old uploader", async () => {
  const old = deferred<ReturnType<typeof permission>>();
  mocks.permission
    .mockReturnValueOnce(old.promise)
    .mockResolvedValue(permission([]));
  const view = mount();
  await waitFor(() => expect(mocks.permission).toHaveBeenCalledTimes(1));
  user = { ...user, leaf_tenant_id: 202 };
  view.refresh();
  await screen.findByText("noOperationPermission");
  user = { ...user, leaf_tenant_id: 101 };
  view.refresh();
  await screen.findByText("noOperationPermission");
  await act(async () => old.resolve(permission()));
  expect(document.querySelector('input[type="file"]')).toBeNull();
  expect(mocks.post).not.toHaveBeenCalled();
});
it("retires late polling results through scope A-B-A", async () => {
  const pending = deferred<ReturnType<typeof page>>();
  mocks.children.mockReturnValue(pending.promise);
  const view = mount();
  await select();
  await waitFor(() => expect(mocks.children).toHaveBeenCalledTimes(1));
  user = { ...user, leaf_tenant_id: 202 };
  view.refresh();
  await waitFor(() =>
    expect(screen.queryByText("report.md")).not.toBeInTheDocument(),
  );
  user = { ...user, leaf_tenant_id: 101 };
  view.refresh();
  await act(async () => pending.resolve(page()));
  expect(screen.queryByText("completed")).not.toBeInTheDocument();
  expect(screen.queryByText("report.md")).not.toBeInTheDocument();
});
it("limits active staging to six and releases cancelled slots even when the old transport ignores abort", async () => {
  const pending = deferred<{ file_path: string; repeat: boolean }>();
  mocks.post.mockReturnValue(pending.promise);
  mount();
  await select(Array.from({ length: 7 }, (_, index) => file(`${index}.md`)));
  await waitFor(() => expect(stageCalls()).toHaveLength(6));
  fireEvent.click(screen.getAllByRole("button", { name: "cancel" })[0]);
  await waitFor(() => expect(stageCalls()).toHaveLength(7));
  expect(stageCalls()[0][2].signal.aborted).toBe(true);
  expect(registerCalls()).toHaveLength(0);
});
