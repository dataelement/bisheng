import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
import { ApiError } from "@bisheng/api-client";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  info: vi.fn(),
  children: vi.fn(),
  parents: vi.fn(),
  permissions: vi.fn(),
  containerEdit: vi.fn(),
  legacy: vi.fn(),
  management: vi.fn(),
  error: vi.fn(),
  preview: vi.fn(),
  copies: vi.fn(),
}));
vi.mock("@/controllers/API/knowledgeCopy", () => ({
  listOwnedSpaceCopies: mocks.copies,
}));
vi.mock("@/controllers/request", () => ({
  default: { get: mocks.get, post: mocks.post },
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
vi.mock("@/pages/KnowledgePage/sidebar/KnowledgeSpaceSidebar", () => ({
  KnowledgeSpaceSidebar: () => null,
}));
vi.mock("@/pages/KnowledgePage/KnowledgeQa", () => ({ default: () => null }));
vi.mock("@/pages/KnowledgePage/components/KnowledgeLibraryDialog", () => ({
  KnowledgeLibraryDialog: () => null,
}));
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
  mocks.copies.mockResolvedValue([]);
  mocks.post.mockResolvedValue({
    check_complete: true,
    can_execute: false,
    valid_items: [],
    invalid_items: [],
    requires_skip_confirmation: false,
    impact: {},
  });
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
      if (url.endsWith("/processing-jobs")) return { data: [], total: 0 };
      if (url.endsWith("/preview")) return mocks.preview(url);
      if (url.includes("/file/info/"))
        return {
          id: 11,
          file_name: "report.pdf",
          knowledge_id: 7,
          user_metadata: {},
        };
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
    expect(screen.queryByText("Description 7")).not.toBeInTheDocument();
    const interaction = userEvent.setup();
    await interaction.hover(
      screen.getByRole("button", { name: "detail.space_info" }),
    );
    const info = await screen.findByRole("tooltip");
    expect(info).toHaveTextContent("ID: 7");
    expect(info).toHaveTextContent("Description 7");
    await interaction.keyboard("{Escape}");
    await waitFor(() => expect(info).not.toBeInTheDocument());
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
    expect(
      screen.queryByRole("button", { name: "f118.processing_title_file" }),
    ).not.toBeInTheDocument();
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
  expect(screen.queryByText("space_copy_ui.recovery_notice")).toBeNull();
  fireEvent.click(await screen.findByRole("button", { name: "report.pdf" }));
  expect(await screen.findByTestId("original-preview")).toBeInTheDocument();
  await waitFor(() => expect(mocks.error).toHaveBeenCalledWith(error));
  expect(
    mocks.get.mock.calls.every(([url]) => !String(url).endsWith("/download")),
  ).toBe(true);
  expect(screen.queryByTestId("legacy-chunks")).not.toBeInTheDocument();
  expect(mocks.containerEdit).not.toHaveBeenCalled();
});

it.each(["preparing", "initializing", "copying"] as const)(
  "shows a themed loading indicator for a %s copy without reading its files",
  async (phase) => {
    mocks.copies.mockResolvedValue([
      {
        id: 7,
        name: "Background copy",
        user_id: 7,
        state: phase === "copying" ? 2 : 0,
        job_id: "original-copy",
        job_state: phase === "preparing" ? "accepted" : "running",
        phase,
        total_count: 10,
        succeeded_count: 0,
        failed_count: 0,
      },
    ]);
    if (phase === "copying") {
      const read = mocks.get.getMockImplementation()!;
      mocks.get.mockImplementation((url: string, ...args: unknown[]) => {
        if (url.endsWith("/processing-jobs/original-copy"))
          return new Promise(() => undefined);
        if (url.endsWith("/processing-jobs/original-copy/items"))
          return { data: [], total: 0 };
        return read(url, ...args);
      });
    }
    mount();
    const title = await screen.findByRole("heading", { name: "Background copy" });
    expect(title).toBeVisible();
    const copyPage = title.closest("section")!;
    expect(within(copyPage).getByRole("status")).toHaveTextContent(`space_copy_ui.phase_${phase}`);
    const spinners = copyPage.querySelectorAll(".bs-tick-spinner.text-primary");
    expect(spinners).toHaveLength(1);
    expect(spinners[0]).toBeVisible();
    expect(within(copyPage).getByText("space_copy_ui.background_notice")).toBeVisible();
    expect(mocks.info).not.toHaveBeenCalled();
    expect(mocks.children).not.toHaveBeenCalled();
  },
);

it("opens a failed copy directly and retries the same job before returning to its files", async () => {
  mocks.copies.mockResolvedValue([
    {
      id: 7,
      name: "Background copy",
      user_id: 7,
      state: 0,
      job_id: "original-copy",
      job_state: "failed",
      phase: "failed",
      total_count: 10,
      succeeded_count: 0,
      failed_count: 10,
    },
  ]);
  const read = mocks.get.getMockImplementation()!;
  const job = {
    id: "original-copy",
    space_id: 7,
    kind: "space_copy",
    state: "failed",
    revision: 1,
    total_count: 10,
    succeeded_count: 0,
    failed_count: 10,
    pending_count: 0,
    hidden_item_count: 10,
    retryable: true,
    error_code: 10996,
  };
  mocks.get.mockImplementation(
    (url: string, options?: { params?: unknown }) => {
      if (url.endsWith("/processing-jobs/original-copy/items"))
        return { data: [], total: 0 };
      if (url.endsWith("/processing-jobs/original-copy")) return job;
      return read(url, options);
    },
  );
  const post = mocks.post.getMockImplementation()!;
  mocks.post.mockImplementation(async (url: string, ...args: unknown[]) => {
    if (!url.endsWith("/processing-jobs/original-copy/retry"))
      return post(url, ...args);
    job.state = "succeeded";
    mocks.copies.mockResolvedValue([]);
    return { job_id: job.id, state: "accepted", accepted: true, reused: false };
  });
  mount();
  const failureTitle = await screen.findByText("space_copy_ui.failed");
  expect(failureTitle).toBeVisible();
  expect(
    failureTitle.closest("section")?.querySelector("[aria-hidden] > .brand-illustration"),
  ).toBeVisible();
  expect(
    screen.queryByText("space_copy_ui.background_notice"),
  ).not.toBeInTheDocument();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "f118.failure_copy_details_missing",
  );
  expect(screen.getByText("f118.processing_hidden")).toBeVisible();
  expect(screen.getByText("f118.processing_task_id")).toBeVisible();
  const failure = within(failureTitle.closest("section")!);
  const retry = failure.getByRole("button", { name: "retry" });
  expect(failure.getAllByRole("button")).toEqual([retry]);
  expect(mocks.children).not.toHaveBeenCalled();
  fireEvent.click(retry);
  await waitFor(() =>
    expect(mocks.post).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/7/processing-jobs/original-copy/retry",
      { expected_job_revision: 1, idempotency_key: expect.any(String), refresh_source: true },
      { params: { kind: "space_copy" } },
    ),
  );
  expect(
    await screen.findByRole("button", { name: "report.pdf" }),
  ).toBeVisible();
});

it("recovers the original copy from a detail page whose target permissions are not initialized", async () => {
  mocks.info.mockRejectedValue(
    new ApiError({ status_code: 25008 }, { message: "Projection not ready" }),
  );
  const read = mocks.get.getMockImplementation()!;
  const job = {
    id: "original-copy",
    space_id: 7,
    kind: "space_copy",
    state: "failed",
    revision: 1,
    accepted_at: "2026-11-16",
    started_at: null,
    finished_at: null,
    total_count: 10,
    succeeded_count: 0,
    failed_count: 10,
    pending_count: 0,
    hidden_item_count: 10,
    retryable: true,
    error_code: 25009,
    obsolete_reason: null,
  };
  mocks.get.mockImplementation(
    (url: string, options?: { params?: unknown }) => {
      if (url.endsWith("/processing-jobs")) return { data: [job], total: 1 };
      if (url.endsWith("/processing-jobs/original-copy/items"))
        return { data: [], total: 0 };
      if (url.endsWith("/processing-jobs/original-copy")) return job;
      return read(url, options);
    },
  );
  const post = mocks.post.getMockImplementation()!;
  mocks.post.mockImplementation(async (url: string, ...args: unknown[]) => {
    if (!url.endsWith("/processing-jobs/original-copy/retry"))
      return post(url, ...args);
    mocks.info.mockResolvedValue({ id: 7, name: "Recovered copy", state: 1 });
    return { job_id: job.id, state: "accepted", accepted: true, reused: false };
  });
  mount();
  const heading = await screen.findByRole("heading", {
    name: "space_copy_ui.tasks",
  });
  expect(screen.getByText("space_copy_ui.recovery_notice")).toBeVisible();
  const recovery = within(heading.closest("section")!);
  fireEvent.click(
    await recovery.findByRole("link", {
      name: "f118.processing_kind_space_copy · f118.processing_state_failed",
    }),
  );
  await recovery.findByText("f118.processing_counts");
  fireEvent.click(await recovery.findByRole("button", { name: "retry" }));
  await waitFor(() =>
    expect(mocks.post).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/7/processing-jobs/original-copy/retry",
      { expected_job_revision: 1, idempotency_key: expect.any(String) },
      { params: { kind: "space_copy" } },
    ),
  );
  expect(await screen.findByText("Recovered copy")).toBeVisible();
  await waitFor(() =>
    expect(screen.queryByText("space_copy_ui.recovery_notice")).toBeNull(),
  );
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
  expect(mocks.permissions).toHaveBeenCalledWith("folder", "9", {
    showError: false,
  });
  const breadcrumb = await screen.findByRole("navigation", {
    name: "f118.current_folder",
  });
  expect(within(breadcrumb).getByText("f118.spaces")).toBeVisible();
  expect(screen.queryByRole("tab", { name: "detail.settings" })).toBeNull();
  expect(mocks.info).not.toHaveBeenCalled();
  expect(mocks.containerEdit).not.toHaveBeenCalled();
});
it("keeps the breadcrumb in the header and preserves filters through folder navigation", async () => {
  mocks.permissions.mockImplementation(async (resourceType: string) =>
    permission(resourceType === "knowledge_space" ? ["visible"] : []),
  );
  const root = "/filelib/7?fileStatus=abnormal&keep=1";
  mount(root);
  fireEvent.click(await screen.findByRole("button", { name: "Folder" }));
  await waitFor(() =>
    expect(screen.getByTestId("location").textContent).toBe(
      `${root}&parent_id=9`,
    ),
  );
  const nav = await screen.findByRole("navigation", {
    name: "f118.current_folder",
  });
  const header = nav.closest("header");
  expect(header).not.toBeNull();
  expect(
    await within(nav).findByRole("button", { name: "Server 7" }),
  ).toBeVisible();
  expect(within(nav).getByText("Child 9")).toHaveAttribute(
    "aria-current",
    "page",
  );

  fireEvent.click(within(header!).getByRole("button", { name: "back" }));
  await waitFor(() =>
    expect(screen.getByTestId("location").textContent).toBe(
      `${root}&parent_id=8`,
    ),
  );
  fireEvent.click(await screen.findByRole("button", { name: "Folder" }));
  const childPath = await screen.findByRole("navigation", {
    name: "f118.current_folder",
  });
  fireEvent.click(within(childPath).getByRole("button", { name: "Parent" }));
  await waitFor(() =>
    expect(screen.getByTestId("location").textContent).toBe(
      `${root}&parent_id=8`,
    ),
  );

  const parentPath = await screen.findByRole("navigation", {
    name: "f118.current_folder",
  });
  fireEvent.click(
    await within(parentPath).findByRole("button", { name: "Server 7" }),
  );
  await waitFor(() =>
    expect(screen.getByTestId("location").textContent).toBe(root),
  );
  expect(
    screen.queryByRole("navigation", { name: "f118.current_folder" }),
  ).toBeNull();
  expect(
    mocks.children.mock.calls.every(
      ([, query]) => query.file_status?.join() === "3,6,7",
    ),
  ).toBe(true);
});

it("keeps the space header and permissions while loading another folder", async () => {
  const nextDirectory = deferred<ReturnType<typeof page>>();
  const nextFolderPermissions = deferred<ReturnType<typeof permission>>();
  mocks.children.mockImplementation(
    async (_url: string, query: { parent_id: number }) =>
      query.parent_id === 42
        ? nextDirectory.promise
        : page([child(11, "previous.pdf"), child(42, "Nested folder", 0)]),
  );
  mocks.permissions.mockImplementation(async (type: string, id: string) => {
    if (type === "knowledge_space") return permission(["edit", "visible"]);
    if (type === "folder" && id === "9") return permission(["create_folder"]);
    if (type === "folder" && id === "42") return nextFolderPermissions.promise;
    return permission();
  });

  mount("/filelib/7?parent_id=9&fileStatus=abnormal&keep=1");
  const more = await screen.findByRole("button", { name: "more" });
  const header = more.closest("header")!;
  const navigation = await within(header).findByRole("navigation", {
    name: "f118.current_folder",
  });
  expect(
    await within(navigation).findByRole("button", { name: "Server 7" }),
  ).toBeVisible();
  expect(
    await within(header).findByRole("button", { name: "detail.add" }),
  ).toBeVisible();
  expect(
    await screen.findByRole("button", { name: "previous.pdf" }),
  ).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Nested folder" }));

  await waitFor(() =>
    expect(mocks.children).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/7/children",
      expect.objectContaining({ parent_id: 42, file_status: [3, 6, 7] }),
    ),
  );
  expect(screen.getByTestId("location").textContent).toBe(
    "/filelib/7?parent_id=42&fileStatus=abnormal&keep=1",
  );
  expect(screen.getByRole("button", { name: "more" })).toBe(more);
  expect(more.closest("header")).toBe(header);
  expect(screen.queryByRole("button", { name: "previous.pdf" })).toBeNull();
  expect(
    within(header).queryByRole("button", { name: "detail.add" }),
  ).toBeNull();
  expect(mocks.permissions).toHaveBeenCalledWith("folder", "9", {
    showError: false,
  });
  expect(mocks.permissions).toHaveBeenCalledWith("folder", "42", {
    showError: false,
  });

  await act(async () => {
    nextFolderPermissions.resolve(permission());
    nextDirectory.resolve(page([child(12, "current.pdf")]));
  });
  expect(
    await screen.findByRole("button", { name: "current.pdf" }),
  ).toBeVisible();
  expect(
    within(header).queryByRole("button", { name: "detail.add" }),
  ).toBeNull();
  expect(mocks.info).toHaveBeenCalledExactlyOnceWith(7);
  expect(
    mocks.permissions.mock.calls.filter(([type]) => type === "knowledge_space"),
  ).toEqual([["knowledge_space", "7", { showError: false }]]);
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

it.each([
  "file_id=0",
  "file_id=11&file_id=12",
  "process_file_id=0",
  "process_file_id=11&process_file_id=12",
])(
  "rejects invalid file targets before reading file or root data: %s",
  async (query) => {
    mount(`/filelib/7?${query}`);
    expect(await screen.findByText("f118.scope_unavailable")).toBeVisible();
    expect(mocks.get).not.toHaveBeenCalled();
  },
);

it.each([false, true])(
  "opens the chunk editor in the ordinary view and preserves directory filters for admin=%s",
  async (isAdmin) => {
    user = { ...user, is_child_admin: isAdmin };
    const current = mount("/filelib/7?parent_id=9&fileStatus=abnormal&keep=1");
    fireEvent.click(await screen.findByRole("button", { name: "report.pdf" }));
    await waitFor(() =>
      expect(screen.getByTestId("detail-chunks")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("location")).toHaveTextContent("file_id=11");
    fireEvent.click(screen.getByRole("button", { name: "back" }));
    expect(
      await screen.findByRole("button", { name: "report.pdf" }),
    ).toBeVisible();
    expect(screen.getByTestId("location")).toHaveTextContent(
      "parent_id=9&fileStatus=abnormal&keep=1",
    );
    expect(screen.getByTestId("location")).not.toHaveTextContent("file_id=");
    const views = current.client
      .getQueryCache()
      .getAll()
      .map((query) => query.queryKey[4]);
    expect(views).toContain("ordinary");
    expect(views).not.toContain("admin");
    expect(screen.getByRole("tab", { name: "f118.spaces" })).toHaveAttribute(
      "data-state",
      "active",
    );
  },
);

it("does not turn a forged management URL into an admin scope for an ordinary user", async () => {
  const current = mount("/filelib/7?view=admin");
  expect(
    await screen.findByRole("button", { name: "report.pdf" }),
  ).toBeVisible();
  expect(screen.queryByRole("tab", { name: "f118.manage_spaces" })).toBeNull();
  const keys = JSON.stringify(
    current.client
      .getQueryCache()
      .getAll()
      .map((query) => query.queryKey),
  );
  expect(keys).toContain("ordinary");
  expect(keys).not.toContain('"admin"');
});

it.each(["accepted", "running", "failed", "partial_failed"])(
  "keeps ready copied space usable while file copy is %s",
  async (state) => {
    const failed = state === "failed" || state === "partial_failed";
    const phase = failed ? "failed" : state === "accepted" ? "preparing" : "copying";
    mocks.copies.mockResolvedValue([
      {
        id: 7,
        name: "Usable copy",
        user_id: 7,
        state: 1,
        job_id: "background-files",
        job_state: state,
        phase,
        total_count: 10,
        succeeded_count: 4,
        failed_count: failed ? 6 : 0,
      },
    ]);
    const itemsUrl = "/api/v1/knowledge/space/7/processing-jobs/background-files/items";
    const failedItem = {
      id: "failed-copy-item",
      file_id: 61,
      file_name: "Failed copy.pdf",
      state: "failed",
      failure_reason: "copy_input_failed",
    };
    const copiedItem = {
      id: "succeeded-copy-item",
      file_id: 62,
      file_name: "Completed copy.pdf",
      state: "succeeded",
    };
    const pendingItem = {
      id: "pending-copy-item",
      file_id: 63,
      file_name: "Pending copy.pdf",
      state: "pending",
    };
    const get = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((url: string, options?: { params?: { state?: string } }) => {
      if (url === itemsUrl) {
        const data = options?.params?.state === "failed" ? [failedItem] : [copiedItem, pendingItem];
        return { data, total: data.length };
      }
      if (url.endsWith("/processing-jobs/background-files"))
        return {
          id: "background-files",
          space_id: 7,
          kind: "space_copy",
          state,
          revision: 1,
          total_count: 10,
          succeeded_count: 4,
          failed_count: failed ? 6 : 0,
          pending_count: failed ? 0 : 6,
          hidden_item_count: 0,
          retryable: failed,
        };
      return get(url, options);
    });
    mount();
    expect(await screen.findByText("report.pdf")).toBeVisible();
    expect(screen.getByText("Folder")).toBeVisible();
    expect(screen.getByText("Server 7")).toBeVisible();
    expect(mocks.children).toHaveBeenCalled();
    const statusLabel =
      state === "partial_failed"
        ? "space_copy_ui.partial_failed"
        : failed
          ? "space_copy_ui.failed"
          : `space_copy_ui.phase_${phase}`;
    expect(screen.getByText(statusLabel)).toBeVisible();
    expect(mocks.get.mock.calls.some(([url]) => url === itemsUrl)).toBe(false);
    expect(screen.queryByRole("table", { name: "space_copy_ui.failure_details" })).not.toBeInTheDocument();
    if (state === "accepted") {
      expect(screen.queryByRole("button", { name: "space_copy_ui.view_details" })).not.toBeInTheDocument();
      expect(screen.queryByRole("region", { name: "space_copy_ui.tasks" })).not.toBeInTheDocument();
      return;
    }
    const disclosure = screen.getByRole("button", { name: "space_copy_ui.view_details" });
    expect(disclosure).toHaveAttribute("aria-expanded", "false");

    const interaction = userEvent.setup();
    if (!failed) {
      await interaction.click(disclosure);
      const details = within(screen.getByRole("region", { name: "space_copy_ui.tasks" }));
      const table = await details.findByRole("table", { name: "f118.processing_items" });
      expect(await within(table).findByRole("rowheader", { name: "Pending copy.pdf" })).toBeVisible();
      expect(details.queryByText(`f118.processing_state_${state}`)).not.toBeInTheDocument();
      expect(details.queryByText("f118.processing_counts")).not.toBeInTheDocument();
      expect(screen.getByText(statusLabel)).toBeVisible();
      return;
    }
    if (state !== "partial_failed") return;

    const retry = await screen.findByRole("button", { name: "retry" });
    expect(retry).toBeVisible();
    expect(disclosure).not.toContainElement(retry);
    await interaction.click(disclosure);
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    const details = within(screen.getByRole("region", { name: "space_copy_ui.tasks" }));
    const table = await details.findByRole("table", { name: "space_copy_ui.failure_details" });
    expect(details.getByRole("heading", { name: "space_copy_ui.failure_details" })).toBeVisible();
    expect(details.queryByRole("radiogroup")).not.toBeInTheDocument();
    expect(await within(table).findByRole("rowheader", { name: "Failed copy.pdf" })).toBeVisible();
    expect(within(table).getByRole("cell", { name: "f118.failure_copy_input_failed" })).toBeVisible();
    expect(within(table).getByText("f118.processing_item_failed").parentElement).toHaveClass("text-danger");
    expect(within(table).queryByRole("rowheader", { name: "Completed copy.pdf" })).not.toBeInTheDocument();
    expect(mocks.get.mock.calls.filter(([url]) => url === itemsUrl)).toEqual([
      [itemsUrl, { params: { kind: "space_copy", page: 1, page_size: 20, state: "failed" } }],
    ]);
    expect(details.queryByRole("button", { name: "retry" })).not.toBeInTheDocument();
    const detailsRegion = screen.getByRole("region", { name: "space_copy_ui.tasks" });
    expect(detailsRegion.querySelector(".brand-illustration")).not.toBeInTheDocument();

    expect(screen.getByRole("button", { name: "report.pdf" })).toBeVisible();
    await interaction.click(disclosure);
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    expect(table).not.toBeInTheDocument();
    expect(retry).toBeVisible();
  },
);
