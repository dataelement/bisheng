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
import { userContext } from "@/contexts/userContext";
import KnowledgePage from "@/pages/KnowledgePage";
import type {
  KnowledgeAdminQuery,
  KnowledgeVisibleQuery,
} from "@/controllers/API/knowledgeSpace";
const pageWindow = window as Window & { LibPage?: { type: string } };

const mocks = vi.hoisted(() => ({
  visible: vi.fn(),
  admin: vi.fn(),
  permission: vi.fn(),
  scope: vi.fn(),
  refresh: vi.fn(),
  legacy: vi.fn(),
  navigate: vi.fn(),
  settings: vi.fn(),
  bootstrap: vi.fn(),
}));
vi.mock("@/contexts/userContext", async () => ({
  userContext: (await import("react")).createContext({ user: {} }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { loadNamespaces: vi.fn(), resolvedLanguage: "en" },
  }),
}));
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => {
      const navigate = actual.useNavigate();
      return (to: string) => { mocks.navigate(to); navigate(to); };
    },
  };
});
// Isolate list authorization/pagination; the real default workspace is tested separately.
vi.mock("@/pages/KnowledgePage/KnowledgeSpaceWorkspace", async () => {
  const { default: KnowledgeFile } = await import("@/pages/KnowledgePage/KnowledgeFile");
  return { KnowledgeSpaceWorkspace: ({ scope }: { scope: import("@/controllers/hooks/knowledge").KnowledgeQueryScope }) => <KnowledgeFile scope={scope} /> };
});
vi.mock("@/pages/KnowledgePage/sidebar/KnowledgeSpaceSidebar", () => ({
  KnowledgeSpaceSidebar: () => <aside data-testid="knowledge-space-tree" />,
}));
vi.mock("@/hooks/useAdminScope", () => ({ useAdminScope: mocks.scope }));
vi.mock("@/controllers/API", () => ({
  readFileLibDatabase: mocks.legacy,
  deleteFileLib: mocks.legacy,
  copyLibDatabase: mocks.legacy,
  getKnowledgeDetailApi: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({
  default: {},
  showApiError: vi.fn(),
}));
vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: mocks.permission,
}));
vi.mock("@/controllers/API/knowledgeSpace", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/controllers/API/knowledgeSpace")>();
  return {
    ...actual,
    knowledgeSpaceApi: {
      ...actual.knowledgeSpaceApi,
      listVisibleSpaces: mocks.visible,
      listAdminSpaces: mocks.admin,
      getProcessingSettings: mocks.settings,
      getCreationSettings: mocks.bootstrap,
    },
  };
});
vi.mock("@/util/hook", () => ({
  useInfiniteCursorTable: () => ({
    data: [],
    loading: false,
    hasMore: false,
    search: vi.fn(),
    reload: vi.fn(),
    loadMore: vi.fn(),
  }),
}));
vi.mock("@/pages/KnowledgePage/KnowledgeQa", () => ({
  default: () => <div data-testid="unchanged-qa" />,
}));
vi.mock("@/controllers/API/finetune", () => ({
  getModelListApi: async () => [
    {
      id: 1,
      name: "Provider",
      models: [
        {
          id: 19,
          model_name: "Embedding",
          model_type: "embedding",
          online: true,
        },
      ],
    },
  ],
}));
vi.mock("@/pages/ModelPage/manage/tabs/WorkbenchModel", () => ({
  ModelSelect: () => null,
}));
vi.mock("@/pages/ModelPage/manage", () => ({
  useModel: () => ({ embeddings: [], isLoading: false }),
}));
vi.mock("@/pages/KnowledgePage/components/FileUploadSplitStrategy", () => ({
  default: () => null,
}));
vi.mock("@/pages/KnowledgePage/components/KnowledgeTooltip", () => ({
  KnowledgeHint: () => null,
  KnowledgeTooltip: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/components/bs-comp/loadMore", () => ({
  default: ({ onScrollLoad }: { onScrollLoad: () => void }) => (
    <button onClick={onScrollLoad}>next-visible-page</button>
  ),
}));
vi.mock("@/components/bs-comp/permission/PermissionDialog", () => ({
  PermissionDialog: ({
    open,
    resourceType,
  }: {
    open: boolean;
    resourceType: string;
  }) =>
    open ? <div data-testid="permission-dialog">{resourceType}</div> : null,
}));
vi.mock("@bisheng/ui", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@bisheng/ui")>();
  return {
    ...actual,
    Dropdown: ({
      children,
      menu,
      open,
      onOpenChange,
    }: {
      children: React.ReactNode;
      menu: React.ReactNode;
      open: boolean;
      onOpenChange: (open: boolean) => void;
    }) => (
      <span
        onClick={(event) => {
          event.stopPropagation();
          onOpenChange(!open);
        }}
      >
        {children}
        {open && <div data-testid="row-menu">{menu}</div>}
      </span>
    ),
    DropdownItem: ({
      children,
      disabled,
      onSelect,
    }: {
      children: React.ReactNode;
      disabled?: boolean;
      onSelect?: () => void;
    }) => (
      <button
        disabled={disabled}
        onClick={(event) => {
          event.stopPropagation();
          onSelect?.();
        }}
      >
        {children}
      </button>
    ),
    DropdownSeparator: () => null,
  };
});
const defaults = {
  schema_version: 1,
  document: {
    split_mode: "auto",
    separator: [""],
    separator_rule: ["after"],
    chunk_size: 300,
    chunk_overlap: 20,
    hierarchy_level: 3,
    append_title: false,
    max_chunk_size: 600,
    retain_images: 1,
    force_ocr: 1,
    enable_formula: 0,
    filter_page_header_footer: 0,
  },
  table: {
    slice_length: 10,
    header_start_row: 1,
    header_end_row: 1,
    append_header: 0,
  },
};
const row = (name = "Space", id = 7) => ({
  id,
  name,
  description: "Description",
  state: 3,
  user_id: 7,
  actions: ["visible"],
  update_time: null,
  user_name: "Creator",
});
const page = (data = [row()]) => ({
  data,
  page_size: 20,
  has_more: false,
  next_cursor: null,
});
const clients: QueryClient[] = [];
let userId = 9000;
beforeEach(() => {
  vi.clearAllMocks();
  mocks.visible.mockResolvedValue(page());
  mocks.admin.mockResolvedValue({
    data: [{ ...row("Admin space"), actions: null }],
    total: 41,
  });
  mocks.permission.mockResolvedValue({
    actions: ["visible", "edit", "manage_permission", "delete"],
  });
  mocks.scope.mockReturnValue({
    scope: { scope_tenant_id: 101, expires_at: null },
    loading: false,
    refresh: mocks.refresh,
  });
  mocks.refresh.mockResolvedValue(undefined);
  mocks.settings.mockResolvedValue({
    space_id: 7,
    config_version: 1,
    saved_defaults: null,
    effective_defaults: defaults,
  });
  mocks.bootstrap.mockResolvedValue({
    embedding_model: { id: "19", name: "Embedding" },
    system_defaults: defaults,
  });
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  delete pageWindow.LibPage;
});
function setup(extra: Record<string, unknown> = {}) {
  const user = {
    user_id: ++userId,
    role: "user",
    tenant_id: 1,
    leaf_tenant_id: 60,
    is_global_super: false,
    is_child_admin: false,
    web_menu: ["create_knowledge"],
    ...extra,
  };
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
  });
  clients.push(client);
  const draw = (value = user) => (
    <QueryClientProvider client={client}>
      <userContext.Provider value={{ user: value } as never}>
        <MemoryRouter initialEntries={["/filelib"]}><KnowledgePage /></MemoryRouter>
      </userContext.Provider>
    </QueryClientProvider>
  );
  return { user, client, draw };
}
const tab = (label: string) =>
  fireEvent.mouseDown(screen.getByRole("tab", { name: label }), {
    button: 0,
    ctrlKey: false,
  });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

it.each(["ordinary", "admin"])(
  "retires %s pagination when abnormal filtering changes, including filter ABA",
  async (view) => {
    const old = deferred<unknown>();
    if (view === "ordinary")
      mocks.visible
        .mockResolvedValueOnce({
          data: [],
          page_size: 20,
          has_more: true,
          next_cursor: "old-cursor",
        })
        .mockReturnValueOnce(old.promise)
        .mockResolvedValue(page([row("Fresh row")]));
    else
      mocks.admin
        .mockResolvedValueOnce({ data: [row("Admin first")], total: 41 })
        .mockReturnValueOnce(old.promise)
        .mockResolvedValue({ data: [row("Fresh row")], total: 41 });
    const f = setup({ is_child_admin: true });
    render(f.draw());
    if (view === "ordinary")
      fireEvent.click(
        await screen.findByRole("button", { name: "next-visible-page" }),
      );
    else {
      await screen.findByText("Space");
      tab("f118.manage_spaces");
      await screen.findByText("Admin first");
      fireEvent.click(screen.getByRole("button", { name: "pagination.next" }));
    }
    const api = view === "ordinary" ? mocks.visible : mocks.admin;
    await waitFor(() => expect(api).toHaveBeenCalledTimes(2));
    const filter = (label: string) => {
      fireEvent.click(
        screen.getByRole("combobox", { name: "fileStatusFilterLabel" }),
      );
      fireEvent.click(screen.getByRole("option", { name: label }));
    };
    filter("fileStatusAbnormal");
    const first =
      view === "ordinary" ? { page_size: 20 } : { page: 1, page_size: 20 };
    const filtered: KnowledgeVisibleQuery | KnowledgeAdminQuery =
      view === "ordinary"
        ? { page_size: 20, has_abnormal: true }
        : { page: 1, page_size: 20, has_abnormal: true };
    await waitFor(() => expect(api).toHaveBeenLastCalledWith(filtered));
    await act(async () =>
      old.resolve(
        view === "ordinary"
          ? page([row("Retired row")])
          : { data: [row("Retired row")], total: 41 },
      ),
    );
    expect(screen.queryByText("Retired row")).toBeNull();
    filter("fileStatusFilterAll");
    await waitFor(() => expect(api).toHaveBeenLastCalledWith(first));
    expect(screen.queryByText("Retired row")).toBeNull();
    filter("fileStatusAbnormal");
    await waitFor(() =>
      expect(api).toHaveBeenLastCalledWith({ ...first, has_abnormal: true }),
    );
    tab("lib.qaData");
    tab(view === "ordinary" ? "f118.spaces" : "f118.manage_spaces");
    await waitFor(() => expect(api).toHaveBeenLastCalledWith(first));
  },
);

it("preserves isolated list authorization, the create menu and the independent QA tab", async () => {
  const f = setup();
  render(f.draw());
  await screen.findByText("Space");
  expect(mocks.visible).toHaveBeenCalledWith({ page_size: 20 });
  expect(mocks.admin).not.toHaveBeenCalled();
  expect(mocks.scope).toHaveBeenCalledWith({ enabled: false });
  expect(mocks.legacy).not.toHaveBeenCalled();
  expect(screen.queryByRole("tab", { name: "f118.manage_spaces" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "create" }));
  await screen.findByRole("spinbutton", { name: "splitLength" });
  expect(mocks.bootstrap).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "cancel" }));
  tab("lib.qaData");
  expect(screen.getByTestId("unchanged-qa")).toBeVisible();
});

it.each([{ is_department_admin: true }, { owner: true }, { role: "admin" }])(
  "does not infer management access from a broader legacy flag %j",
  async (extra) => {
    const f = setup({ ...extra, web_menu: [] });
    render(f.draw());
    await screen.findByText("Space");
    expect(
      screen.queryByRole("tab", { name: "f118.manage_spaces" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "create" })).toBeNull();
    expect(mocks.admin).not.toHaveBeenCalled();
  },
);

it.each(["super", "tenant-admin"])(
  "uses the concrete trusted execution tenant for %s and server pagination",
  async (role) => {
    const f = setup(
      role === "super"
        ? { is_global_super: true, leaf_tenant_id: 1 }
        : { is_child_admin: true, web_menu: [] },
    );
    render(f.draw());
    await screen.findByText("Space");
    tab("f118.manage_spaces");
    await screen.findByText("Admin space");
    expect(mocks.admin).toHaveBeenCalledWith({ page: 1, page_size: 20 });
    expect(
      f.client
        .getQueryCache()
        .findAll()
        .some(
          (query) =>
            query.queryKey[0] === "f118-knowledge" &&
            query.queryKey[2] === (role === "super" ? 101 : 60) &&
            query.queryKey[3] === (role === "super" ? 101 : 60),
        ),
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "pagination.next" }));
    await waitFor(() =>
      expect(mocks.admin).toHaveBeenCalledWith({ page: 2, page_size: 20 }),
    );
    expect(mocks.permission).not.toHaveBeenCalled();
  },
);

it("never substitutes a super's home or leaf while its server management pin is unknown", async () => {
  mocks.scope.mockReturnValue({
    scope: { scope_tenant_id: null },
    loading: false,
    refresh: mocks.refresh,
  });
  const f = setup({ is_global_super: true, leaf_tenant_id: 1 }),
    view = render(f.draw());
  expect(screen.getByText("f118.scope_unavailable")).toBeVisible();
  expect(mocks.visible).not.toHaveBeenCalled();
  expect(mocks.admin).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "create" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await waitFor(() => expect(mocks.refresh).toHaveBeenCalledTimes(1));
  mocks.scope.mockReturnValue({
    scope: { scope_tenant_id: 202 },
    loading: false,
    refresh: mocks.refresh,
  });
  view.rerender(f.draw());
  await screen.findByText("Space");
  expect(
    f.client
      .getQueryCache()
      .findAll()
      .some((query) => query.queryKey[2] === 202 && query.queryKey[3] === 202),
  ).toBe(true);
});

it("blocks unknown ordinary membership and ignores a forged persisted admin tab", () => {
  pageWindow.LibPage = { type: "admin" } as typeof pageWindow.LibPage;
  const f = setup({ leaf_tenant_id: undefined, web_menu: [] });
  render(f.draw());
  expect(screen.getByText("f118.scope_unavailable")).toBeVisible();
  expect(mocks.visible).not.toHaveBeenCalled();
  expect(mocks.admin).not.toHaveBeenCalled();
});

it("advances an empty ordinary cursor page without inventing a total and resets the cursor on search", async () => {
  mocks.visible
    .mockResolvedValueOnce({
      data: [],
      page_size: 20,
      has_more: true,
      next_cursor: "opaque/+==",
    })
    .mockResolvedValue(page([row("Visible after gap")]));
  const f = setup();
  render(f.draw());
  fireEvent.click(
    await screen.findByRole("button", { name: "next-visible-page" }),
  );
  await screen.findByText("Visible after gap");
  expect(mocks.visible).toHaveBeenNthCalledWith(2, {
    page_size: 20,
    cursor: "opaque/+==",
  });
  fireEvent.change(screen.getByPlaceholderText("lib.searchPlaceholder"), {
    target: { value: "New" },
  });
  await waitFor(() =>
    expect(mocks.visible).toHaveBeenLastCalledWith({
      page_size: 20,
      keyword: "New",
    }),
  );
  expect(
    screen.queryByRole("navigation", { name: "pagination.nav" }),
  ).toBeNull();
});

it("loads SPACE actions lazily, routes defaults into its tab and leaves copy/delete unavailable", async () => {
  const f = setup({ is_child_admin: true }),
    view = render(f.draw());
  await screen.findByText("Space");
  expect(mocks.permission).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "more" }));
  await screen.findByRole("button", { name: "f118.defaults_title" });
  expect(mocks.permission).toHaveBeenCalledWith("knowledge_space", "7");
  expect(screen.queryByRole("button", { name: "delete" })).toBeNull();
  expect(screen.queryByRole("button", { name: "lib.copy" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "f118.defaults_title" }));
  expect(mocks.navigate).toHaveBeenCalledWith("/filelib/7?tab=defaults");
  expect(mocks.settings).not.toHaveBeenCalled();
  view.rerender(f.draw({ ...f.user, user_id: f.user.user_id + 1000 }));
  await screen.findByText("Space");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(mocks.legacy).not.toHaveBeenCalled();
});

it("does not fabricate business actions for an admin row with a null action projection", async () => {
  mocks.permission.mockResolvedValueOnce({ actions: ["visible"] });
  const f = setup({ is_global_super: true });
  render(f.draw());
  await screen.findByText("Space");
  tab("f118.manage_spaces");
  await screen.findByText("Admin space");
  fireEvent.click(screen.getByRole("button", { name: "more" }));
  await waitFor(() => expect(mocks.permission).toHaveBeenCalled());
  expect(screen.queryByRole("button", { name: "settings" })).toBeNull();
  expect(
    screen.queryByRole("button", { name: "f118.defaults_title" }),
  ).toBeNull();
});

it.each(["super", "tenant-admin"])("retains the management view when %s opens a space or its configuration", async (role) => {
  const f = setup(role === "super" ? { is_global_super: true } : { is_child_admin: true });
  render(f.draw());
  await screen.findByText("Space");
  tab("f118.manage_spaces");
  fireEvent.click(await screen.findByText("Admin space"));
  await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith("/filelib/7?view=admin"));
  expect(mocks.permission).toHaveBeenCalledWith("knowledge_space", "7");
  fireEvent.click(screen.getByRole("button", { name: "more" }));
  fireEvent.click(await screen.findByRole("button", { name: "f118.defaults_title" }));
  expect(mocks.navigate).toHaveBeenCalledWith("/filelib/7?tab=defaults&view=admin");
  expect(mocks.settings).not.toHaveBeenCalled();
});

it("retires a previous scope's row menu and late permission response", async () => {
  const permission = deferred<{ actions: string[] }>();
  mocks.permission.mockReturnValueOnce(permission.promise);
  const f = setup({ is_global_super: true }),
    view = render(f.draw());
  await screen.findByText("Space");
  fireEvent.click(screen.getByRole("button", { name: "more" }));
  await waitFor(() => expect(mocks.permission).toHaveBeenCalledTimes(1));
  mocks.visible.mockResolvedValueOnce(page([row("New tenant space", 8)]));
  mocks.scope.mockReturnValue({
    scope: { scope_tenant_id: 202 },
    loading: false,
    refresh: mocks.refresh,
  });
  view.rerender(f.draw());
  await screen.findByText("New tenant space");
  await act(async () =>
    permission.resolve({ actions: ["edit", "manage_permission"] }),
  );
  expect(screen.queryByTestId("row-menu")).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
});
