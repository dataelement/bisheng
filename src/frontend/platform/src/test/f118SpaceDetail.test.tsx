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
import KnowledgePage from "@/pages/KnowledgePage";
import Header from "@/pages/KnowledgePage/components/Header";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  info: vi.fn(),
  children: vi.fn(),
  parents: vi.fn(),
  permissions: vi.fn(),
  containerEdit: vi.fn(),
  legacy: vi.fn(),
  management: vi.fn(),
  error: vi.fn(),
  preview: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({
  default: { get: mocks.get },
  showApiError: mocks.error,
}));
vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: mocks.permissions,
  checkResourceActionApi: mocks.containerEdit,
}));
vi.mock("@/controllers/API", () => ({ updateKnowledgeApi: mocks.legacy }));
vi.mock("@/contexts/userContext", async () => ({
  userContext: (await import("react")).createContext({ user: null }),
}));
vi.mock("@/hooks/useAdminScope", () => ({ useAdminScope: mocks.management }));
vi.mock("@/pages/KnowledgePage/sidebar/KnowledgeSpaceSidebar", () => ({ KnowledgeSpaceSidebar: () => null }));
vi.mock("@/pages/KnowledgePage/KnowledgeFile", () => ({ default: () => null }));
vi.mock("@/pages/KnowledgePage/KnowledgeQa", () => ({ default: () => null }));
vi.mock("@/pages/KnowledgePage/components/KnowledgeLibraryDialog", () => ({ KnowledgeLibraryDialog: () => null }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: "en", loadNamespaces: vi.fn() },
  }),
}));
vi.mock("@/pages/KnowledgePage/components/PreviewParagraph", () => ({
  default: () => <output data-testid="detail-chunks" />,
}));
vi.mock("@/pages/KnowledgePage/components/PreviewFile", () => ({
  default: () => <output data-testid="original-preview" />,
}));

let user: Partial<User> | null;
let management: {
  scope: { scope_tenant_id: number | null; expires_at: null };
  loading: boolean;
  refresh: ReturnType<typeof vi.fn>;
};
const clients: QueryClient[] = [];
const child = (id = 11, name = "report.pdf", file_type = 1) => ({
  id,
  knowledge_id: 7,
  file_name: name,
  file_type,
  status: 2,
});
const page = (data = [child(), child(9, "Folder", 0)]) => ({
  data,
  page_size: 40,
  has_more: false,
  next_cursor: null,
});
const permission = (actions: string[] = []) => ({
  actions,
  mode: "INHERIT",
  sources: [],
  roster_complete: true,
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}
function mount(path = "/filelib/7") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
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
            <Route path="/filelib/:id" element={<KnowledgePage />} />
            <Route path="/filelib" element={<p>space-list</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </userContext.Provider>
  );
  const result = render(view());
  return {
    client,
    go: (next: string) => act(() => navigate(next)),
    refresh: () => result.rerender(view()),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  const storage = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
    clear: () => storage.clear(),
    key: (index: number) => [...storage.keys()][index] ?? null,
    get length() {
      return storage.size;
    },
  });
  user = { user_id: 7, tenant_id: 1, leaf_tenant_id: 101 };
  management = {
    scope: { scope_tenant_id: 202, expires_at: null },
    loading: false,
    refresh: vi.fn().mockResolvedValue(undefined),
  };
  mocks.management.mockImplementation(() => management);
  mocks.containerEdit.mockResolvedValue({ allowed: true });
  mocks.permissions.mockResolvedValue(permission());
  mocks.info.mockImplementation(async (id: number) => ({
    id,
    name: `Server ${id}`,
    description: `Description ${id}`,
    actions: [],
  }));
  mocks.children.mockResolvedValue(page());
  mocks.parents.mockImplementation(async (_sid: number, id: number) =>
    id === 8
      ? [{ id: 8, file_name: "Parent" }]
      : [
          { id: 8, file_name: "Parent" },
          { id, file_name: `Child ${id}` },
        ],
  );
  mocks.preview.mockResolvedValue({
    original_url: "https://objects.test/read.pdf",
    preview_url: "",
  });
  mocks.get.mockImplementation(
    (url: string, options?: { params?: unknown }) => {
      const info = url.match(/space\/(\d+)\/info$/);
      if (info) return mocks.info(Number(info[1]));
      const parents = url.match(/space\/(\d+)\/folders\/(\d+)\/parent$/);
      if (parents) return mocks.parents(Number(parents[1]), Number(parents[2]));
      if (url.endsWith("/children"))
        return mocks.children(url, options?.params);
      if (url.endsWith("/preview")) return mocks.preview(url);
      if (url.includes("/file/info/")) return { id: 11, file_name: "report.pdf", knowledge_id: 7, user_metadata: {} };
      if (url.endsWith("/chunk")) return { data: [], total: 0 };
      if (url.endsWith("/file_bbox")) return {};
      throw new Error(`unexpected API read: ${url}`);
    },
  );
  Object.assign(window, {
    libname: ["Unscoped private title", "Unscoped private description"],
  });
  localStorage.setItem("libname", "Persisted private title");
  localStorage.setItem("libdesc", "Persisted private description");
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  Reflect.deleteProperty(window, "libname");
  localStorage.removeItem("libname");
  localStorage.removeItem("libdesc");
  vi.unstubAllGlobals();
});

it.each([false, true])(
  "mounts ordinary SPACE APIs with actual scope, super=%s",
  async (superAdmin) => {
    user = { ...user, is_global_super: superAdmin };
    const view = mount();
    expect(await screen.findByText("Server 7")).toBeInTheDocument();
    expect(screen.getByText("ID: 7 · Description 7")).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "report.pdf" }),
    ).toBeInTheDocument();
    const key = view.client
      .getQueryCache()
      .findAll()
      .map((query) => query.queryKey);
    expect(JSON.stringify(key)).toContain(superAdmin ? "202" : "101");
    expect(JSON.stringify(key)).toContain("ordinary");
    expect(user?.tenant_id).toBe(1);
    expect(mocks.containerEdit).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "f118.processing_title_file" })).not.toBeInTheDocument();
    expect(
      screen.queryByText("Unscoped private title"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Persisted private title"),
    ).not.toBeInTheDocument();
    expect(mocks.legacy).not.toHaveBeenCalled();
  },
);
it("mounts visible-only child content when root info fails and never enters legacy chunks", async () => {
  const error = { status_code: 19000, marker: "original error" };
  mocks.info.mockRejectedValue(error);
  mocks.containerEdit.mockResolvedValue({ allowed: false });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "report.pdf" }));
  expect(await screen.findByTestId("original-preview")).toBeInTheDocument();
  await waitFor(() => expect(mocks.error).toHaveBeenCalledWith(error));
  expect(
    mocks.get.mock.calls.every(([url]) => !String(url).endsWith("/download")),
  ).toBe(true);
  expect(screen.queryByTestId("legacy-chunks")).not.toBeInTheDocument();
  expect(mocks.containerEdit).not.toHaveBeenCalled();
});
it("direct child admission uses current folder facts without a root info or visible precondition", async () => {
  mocks.containerEdit.mockResolvedValue({ allowed: false });
  mount("/filelib/7?parent_id=9");
  expect(
    await screen.findByRole("button", { name: "report.pdf" }),
  ).toBeInTheDocument();
  expect(await screen.findAllByText("Child 9")).not.toHaveLength(0);
  expect(mocks.parents).toHaveBeenCalledWith(7, 9);
  expect(mocks.children).toHaveBeenCalledWith(
    "/api/v1/knowledge/space/7/children",
    expect.objectContaining({ parent_id: 9 }),
  );
  expect(mocks.permissions).toHaveBeenCalledWith("folder", "9");
  expect(screen.queryByRole("tab", { name: "detail.settings" })).toBeNull();
  expect(mocks.info).not.toHaveBeenCalled();
  expect(mocks.containerEdit).not.toHaveBeenCalled();
});
it("updates only parent_id for folder and breadcrumb navigation and keeps the old status filter", async () => {
  mount("/filelib/7?fileStatus=abnormal");
  fireEvent.click(await screen.findByRole("button", { name: "Folder" }));
  await waitFor(() =>
    expect(screen.getByTestId("location")).toHaveTextContent(
      "fileStatus=abnormal&parent_id=9",
    ),
  );
  const nav = await screen.findByRole("navigation", {
    name: "f118.current_folder",
  });
  fireEvent.click(within(nav).getByRole("button", { name: "Parent" }));
  await waitFor(() => expect(mocks.parents).toHaveBeenCalledWith(7, 8));
  fireEvent.click(
    within(
      await screen.findByRole("navigation", { name: "f118.current_folder" }),
    ).getByRole("button", { name: "f118.spaces" }),
  );
  await waitFor(() =>
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/filelib/7?fileStatus=abnormal",
    ),
  );
  expect(
    mocks.children.mock.calls.every(
      ([, query]) => query.file_status?.join() === "3,6,7",
    ),
  ).toBe(true);
});
it.each([
  "/filelib/0",
  "/filelib/nope",
  "/filelib/7?parent_id=",
  "/filelib/7?parent_id=-1",
  "/filelib/7?parent_id=9&parent_id=9",
  "/filelib/7?parent_id=9007199254740992",
  "/filelib/7?parent_id=1e2",
])("rejects invalid route identifiers before any read: %s", async (path) => {
  mount(path);
  expect(await screen.findByText("f118.scope_unavailable")).toBeInTheDocument();
  expect(mocks.get).not.toHaveBeenCalled();
  expect(mocks.permissions).not.toHaveBeenCalled();
  expect(mocks.containerEdit).not.toHaveBeenCalled();
});
it("waits for a trusted super management tenant before issuing any resource request", async () => {
  user = { ...user, is_global_super: true };
  management = {
    ...management,
    scope: { ...management.scope, scope_tenant_id: null },
    loading: true,
  };
  const view = mount();
  expect(mocks.get).not.toHaveBeenCalled();
  management = {
    ...management,
    scope: { ...management.scope, scope_tenant_id: 202 },
    loading: false,
  };
  view.refresh();
  expect(await screen.findByText("Server 7")).toBeInTheDocument();
});
it("retires delayed info through route ABA instead of reusing a previous opening's title", async () => {
  const old = deferred<{ id: number; name: string }>();
  mocks.info
    .mockReturnValueOnce(old.promise)
    .mockResolvedValueOnce({ id: 8, name: "Current eight" })
    .mockResolvedValue({ id: 7, name: "New seven" });
  const view = mount();
  await waitFor(() => expect(mocks.info).toHaveBeenCalledWith(7));
  await view.go("/filelib/8");
  expect(await screen.findByText("Current eight")).toBeInTheDocument();
  await view.go("/filelib/7");
  expect(await screen.findByText("New seven")).toBeInTheDocument();
  await act(async () => old.resolve({ id: 7, name: "Retired seven" }));
  expect(screen.queryByText("Retired seven")).not.toBeInTheDocument();
  expect(mocks.info).toHaveBeenCalledTimes(3);
});
it("retires delayed breadcrumb names across folder ABA", async () => {
  const old = deferred<{ id: number; file_name: string }[]>();
  mocks.parents
    .mockReturnValueOnce(old.promise)
    .mockResolvedValueOnce([{ id: 42, file_name: "Current folder" }])
    .mockResolvedValue([{ id: 9, file_name: "New nine" }]);
  const view = mount("/filelib/7?parent_id=9");
  await waitFor(() => expect(mocks.parents).toHaveBeenCalledWith(7, 9));
  await view.go("/filelib/7?parent_id=42");
  expect(await screen.findAllByText("Current folder")).not.toHaveLength(0);
  await view.go("/filelib/7?parent_id=9");
  expect(await screen.findAllByText("New nine")).not.toHaveLength(0);
  await act(async () => old.resolve([{ id: 9, file_name: "Retired nine" }]));
  expect(screen.queryByText("Retired nine")).not.toBeInTheDocument();
  expect(mocks.info).not.toHaveBeenCalled();
});
it("keeps an empty controlled Header authoritative while old consumers retain their legacy title", async () => {
  const view = render(
    <MemoryRouter>
      <Header fileTitle title="" description="" />
    </MemoryRouter>,
  );
  expect(screen.queryByText("Unscoped private title")).not.toBeInTheDocument();
  expect(localStorage.getItem("libname")).toBe("Persisted private title");
  view.rerender(
    <MemoryRouter>
      <Header fileTitle />
    </MemoryRouter>,
  );
  expect(await screen.findByText("Unscoped private title")).toBeInTheDocument();
});
it.each(["tenant", "identity"])(
  "does not consume an old title after a %s partition change",
  async (change) => {
    const old = deferred<{ id: number; name: string }>();
    mocks.info
      .mockReturnValueOnce(old.promise)
      .mockResolvedValue({ id: 7, name: "Current scoped title" });
    const view = mount();
    await waitFor(() => expect(mocks.info).toHaveBeenCalledOnce());
    user =
      change === "tenant"
        ? { ...user, leaf_tenant_id: 202 }
        : { ...user, user_id: 8 };
    view.refresh();
    expect(await screen.findByText("Current scoped title")).toBeInTheDocument();
    await act(async () => old.resolve({ id: 7, name: "Retired scoped title" }));
    expect(screen.queryByText("Retired scoped title")).not.toBeInTheDocument();
  },
);
it("does not fill a hidden root shell from legacy title storage", async () => {
  mocks.info.mockResolvedValue({
    id: 7,
    name: "",
    description: "",
    actions: [],
  });
  mount();
  expect(
    await screen.findByRole("button", { name: "report.pdf" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("Unscoped private title")).not.toBeInTheDocument();
  expect(screen.queryByText("Persisted private title")).not.toBeInTheDocument();
  expect(localStorage.getItem("libname")).toBe("Persisted private title");
});
it("preserves the server's numeric fallback for a missing ancestor", async () => {
  mocks.parents.mockResolvedValue([
    { id: 8, file_name: 8 },
    { id: 9, file_name: "Current" },
  ]);
  mount("/filelib/7?parent_id=9");
  const nav = await screen.findByRole("navigation", {
    name: "f118.current_folder",
  });
  expect(within(nav).getByRole("button", { name: "8" })).toBeInTheDocument();
  expect(await screen.findAllByText("Current")).not.toHaveLength(0);
  expect(mocks.info).not.toHaveBeenCalled();
});
it("updates the actual directory filter for a same-parent URL status change", async () => {
  const view = mount("/filelib/7?parent_id=9&keep=1");
  await screen.findByRole("button", { name: "report.pdf" });
  mocks.children.mockClear();
  await view.go("/filelib/7?parent_id=9&keep=1&fileStatus=abnormal");
  await waitFor(() =>
    expect(mocks.children).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/7/children",
      expect.objectContaining({ parent_id: 9, file_status: [3, 6, 7] }),
    ),
  );
  expect(screen.getByTestId("location")).toHaveTextContent("keep=1");
});
it("restores all-file requests when the URL abnormal filter is removed", async () => {
  const view = mount("/filelib/7?parent_id=9&keep=1&fileStatus=abnormal");
  await screen.findByRole("button", { name: "report.pdf" });
  expect(mocks.children.mock.lastCall?.[1].file_status).toEqual([3, 6, 7]);
  mocks.children.mockClear();
  await view.go("/filelib/7?parent_id=9&keep=1");
  await waitFor(() => expect(mocks.children).toHaveBeenCalled());
  expect(mocks.children.mock.lastCall?.[1].file_status).toBeUndefined();
  expect(screen.getByTestId("location")).toHaveTextContent("keep=1");
});
it("retires a delayed abnormal page across fileStatus URL ABA", async () => {
  const pending = deferred<ReturnType<typeof page>>();
  mocks.children
    .mockResolvedValueOnce(page([child(11, "first-normal.pdf")]))
    .mockReturnValueOnce(pending.promise)
    .mockResolvedValue(page([child(13, "latest-normal.pdf")]));
  const view = mount("/filelib/7?parent_id=9&keep=1");
  await screen.findByRole("button", { name: "first-normal.pdf" });
  await view.go("/filelib/7?parent_id=9&keep=1&fileStatus=abnormal");
  await waitFor(() => expect(mocks.children).toHaveBeenCalledTimes(2));
  await view.go("/filelib/7?parent_id=9&keep=1");
  await screen.findByRole("button", { name: "latest-normal.pdf" });
  await act(async () =>
    pending.resolve(page([child(12, "retired-abnormal.pdf")])),
  );
  expect(screen.queryByText("retired-abnormal.pdf")).not.toBeInTheDocument();
  expect(mocks.children).toHaveBeenCalledTimes(3);
});

it.each(["file_id=0", "file_id=11&file_id=12"])("rejects invalid file targets before reading file or root data: %s", async (query) => {
  mount(`/filelib/7?${query}`);
  expect(await screen.findByText("f118.scope_unavailable")).toBeVisible();
  expect(mocks.get).not.toHaveBeenCalled();
});

it.each(["ordinary", "admin"])("opens the chunk editor in the %s view and returns to the same directory with its original filters", async (view) => {
  user = { ...user, is_child_admin: view === "admin" };
  const current = mount(`/filelib/7?parent_id=9&fileStatus=abnormal&keep=1${view === "admin" ? "&view=admin" : ""}`);
  fireEvent.click(await screen.findByRole("button", { name: "report.pdf" }));
  await waitFor(() => expect(screen.getByTestId("detail-chunks")).toBeInTheDocument());
  expect(screen.getByTestId("location")).toHaveTextContent("file_id=11");
  fireEvent.click(screen.getByRole("button", { name: "back" }));
  expect(await screen.findByRole("button", { name: "report.pdf" })).toBeVisible();
  expect(screen.getByTestId("location")).toHaveTextContent("parent_id=9&fileStatus=abnormal&keep=1");
  expect(screen.getByTestId("location")).not.toHaveTextContent("file_id=");
  const views = current.client.getQueryCache().getAll().map((query) => query.queryKey[4]);
  expect(views).toContain(view);
  expect(views).not.toContain(view === "admin" ? "ordinary" : "admin");
  expect(screen.getByRole("tab", { name: view === "admin" ? "f118.manage_spaces" : "f118.spaces" })).toHaveAttribute("data-state", "active");
});

it("does not turn a forged management URL into an admin scope for an ordinary user", async () => {
  const current = mount("/filelib/7?view=admin");
  expect(await screen.findByRole("button", { name: "report.pdf" })).toBeVisible();
  expect(screen.queryByRole("tab", { name: "f118.manage_spaces" })).toBeNull();
  const keys = JSON.stringify(current.client.getQueryCache().getAll().map((query) => query.queryKey));
  expect(keys).toContain("ordinary");
  expect(keys).not.toContain('"admin"');
});
