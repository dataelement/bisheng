import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentProps } from "react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import KnowledgePage from "@/pages/KnowledgePage";
import { KnowledgeSpaceCreatePage } from "@/pages/KnowledgePage/KnowledgeSpaceCreatePage";
import { KnowledgeSpaceSettingsPage } from "@/pages/KnowledgePage/KnowledgeSpaceSettingsPage";
import { userContext } from "@/contexts/userContext";
import type { FilesProps } from "@/pages/KnowledgePage/components/Files";
import type { CreateSpaceForm } from "@/pages/KnowledgePage/components/KnowledgeLibraryDialog";
import type { SpaceSettingsEditor } from "@/pages/KnowledgePage/components/SpaceSettingsEditor";
import type { User } from "@/types/api/user";

const mock = vi.hoisted(() => ({ get: vi.fn(), permissions: vi.fn(), scope: vi.fn() }));
vi.mock("@/contexts/userContext", async () => ({ userContext: (await import("react")).createContext({ user: {} }) }));
vi.mock("@/hooks/useKnowledgePageScope", () => ({ useKnowledgePageScope: mock.scope }));
vi.mock("@/controllers/API/permission", () => ({ getMyResourcePermissionsApi: mock.permissions }));
vi.mock("@/controllers/request", () => ({ default: { get: mock.get }, showApiError: vi.fn() }));
vi.mock("@/pages/KnowledgePage/KnowledgeQa", () => ({ default: () => <p>qa-list</p> }));
vi.mock("@/pages/KnowledgePage/components/SpaceSettingsEditor", () => ({
  SpaceSettingsEditor: ({ scope: formScope, onBack, onSaved }: ComponentProps<typeof SpaceSettingsEditor>) => (
    <section>
      <p>settings-editor</p>
      <output data-testid="settings-scope">{JSON.stringify(formScope)}</output>
      {onBack && (
        <>
          <button type="button" onClick={onBack}>back</button>
          <button type="button" onClick={onBack}>cancel</button>
          <button type="button" onClick={async () => { await onSaved(); onBack(); }}>confirm</button>
        </>
      )}
    </section>
  ),
}));
vi.mock("@/pages/KnowledgePage/components/KnowledgeLibraryDialog", () => ({
  CreateSpaceForm: ({ presentation, scope: formScope, onCancel }: ComponentProps<typeof CreateSpaceForm>) => (
    <section role={presentation === "page" ? undefined : "dialog"}>
      <h1>f118.create_space</h1>
      <output data-testid="creation-scope">{JSON.stringify(formScope)}</output>
      <button type="button" onClick={onCancel}>cancel</button>
    </section>
  ),
}));
vi.mock("@/pages/KnowledgePage/components/Files", () => ({ default: (props: FilesProps) => <output data-testid="files">{JSON.stringify({ id: props.spaceId, parent: props.parentId, presentation: props.presentation, view: props.scope?.view })}</output> }));

const scope = { identityKey: "user:5", tenantId: 60, managementTenantId: 60, view: "ordinary" } as const;
const clients: QueryClient[] = [];
function Location() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><output data-testid="location">{location.pathname}{location.search}</output><button onClick={() => navigate(-1)}>history-back</button><button onClick={() => navigate(1)}>history-forward</button></>;
}
function mount(path = "/filelib", user: Partial<User> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <userContext.Provider value={{ user: { user_id: 5, ...user }, setUser: vi.fn(), savedComponents: [], addSavedComponent: async () => undefined, checkComponentsName: () => false, delComponent: vi.fn() }}>
        <MemoryRouter initialEntries={[path]}>
          <Location />
          <Routes>
            <Route path="/filelib" element={<KnowledgePage />} />
            <Route path="/filelib/create" element={<KnowledgeSpaceCreatePage />} />
            <Route path="/filelib/:id/settings" element={<KnowledgeSpaceSettingsPage />} />
            <Route path="/filelib/:id" element={<KnowledgePage />} />
          </Routes>
        </MemoryRouter>
      </userContext.Provider>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  mock.permissions.mockResolvedValue({ actions: [] });
  mock.scope.mockReturnValue({ scopes: { ordinary: scope, admin: { ...scope, view: "admin" } }, canManage: true, isLoading: false, retry: vi.fn() });
  mock.get.mockImplementation(async (url: string, options?: { params?: { file_type?: number; parent_id?: number | null } }) => {
    if (url.endsWith("/admin/list")) return { data: [{ id: 7, name: "Reports", tenant_id: 60, space_kind: "normal" }], total: 1 };
    if (url.endsWith("/copy/tasks")) return { data: [], total: 0 };
    if (url.endsWith("/mine")) return [{ id: 7, name: "Reports", tenant_id: 60 }];
    if (url.endsWith("/joined") || url.endsWith("/department")) return [];
    if (url.endsWith("/children") && options?.params?.file_type === 0) return { data: options.params.parent_id == null ? [{ id: 9, file_name: "Finance", file_type: 0 }] : [], has_more: false, next_cursor: null };
    if (url.endsWith("/info")) return { id: 7, name: "Reports", description: "Latest reports" };
    if (url.endsWith("/parent")) return [{ id: 9, file_name: "Finance" }];
    if (url.endsWith("/metadata-schema")) return { revision: 5, fields: [] };
    if (url.endsWith("/processing-jobs")) return { data: [], total: 0 };
    throw new Error(`Unexpected read ${url}`);
  });
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); Reflect.deleteProperty(window, "LibPage"); });

it("keeps the expanded tree and routes selected folders into the workspace file presentation", async () => {
  mount("/filelib?fileStatus=abnormal&keep=1");
  const tree = screen.getByRole("complementary");
  await screen.findByTestId("files");
  fireEvent.click(await within(tree).findByRole("button", { name: "Finance" }));
  await waitFor(() => expect(screen.getByTestId("files")).toHaveTextContent('"parent":9'));
  expect(screen.getByTestId("location")).toHaveTextContent("/filelib/7?fileStatus=abnormal&keep=1&parent_id=9");
  expect(screen.getByTestId("files")).toHaveTextContent('"presentation":"workspace"');
  expect(screen.getByRole("button", { name: "back" })).toBeVisible();
  expect(within(screen.getByRole("complementary")).getByRole("button", { name: "Finance" })).toHaveAttribute("aria-current", "page");
  expect(screen.queryByText("ordinary-list")).toBeNull();
  expect(screen.queryByRole("button", { name: "sidebar.all_spaces" })).toBeNull();
});

it("opens deep folder links while preserving the independent QA and management tabs", async () => {
  mount("/filelib/7?parent_id=9");
  expect(await screen.findByTestId("files")).toHaveTextContent('"parent":9');
  const tree = screen.getByRole("complementary");
  expect(await within(tree).findByRole("button", { name: "Finance" })).toHaveAttribute("aria-current", "page");
  const path = await screen.findByRole("navigation", { name: "f118.current_folder" });
  expect(within(path).getByText("Finance")).toHaveAttribute("aria-current", "page");
  expect(mock.get.mock.calls.filter(([url]) => url.endsWith("/space/7/folders/9/parent"))).toHaveLength(1);
  fireEvent.mouseDown(screen.getByRole("tab", { name: "lib.qaData" }), { button: 0, ctrlKey: false });
  expect(await screen.findByText("qa-list")).toBeVisible();
  fireEvent.mouseDown(screen.getByRole("tab", { name: "f118.manage_spaces" }), { button: 0, ctrlKey: false });
  expect(await screen.findByRole("table", { name: "f118.manage_spaces" })).toBeVisible();
  expect(screen.queryByRole("complementary")).toBeNull();
  expect(screen.queryByTestId("files")).toBeNull();
});

it("rejects invalid directory links without loading their file content", async () => {
  mount("/filelib/7?parent_id=9&parent_id=10");
  expect(screen.getByText("f118.scope_unavailable")).toBeVisible();
  expect(screen.queryByTestId("files")).toBeNull();
  await screen.findByRole("button", { name: "Reports" });
  expect(mock.get.mock.calls.some(([url]) => String(url).endsWith("/info"))).toBe(false);
});

it.each(["cancel", "confirm"])("opens standalone space settings and returns to the folder on %s", async (action) => {
  mock.permissions.mockResolvedValue({ actions: ["edit"] });
  const directory = "/filelib/7?parent_id=9&fileStatus=abnormal&keep=1";
  mount(directory);
  expect(await screen.findByTestId("files")).toHaveTextContent('"parent":9');
  const header = (await screen.findByRole("navigation", { name: "f118.current_folder" })).closest("header")!;
  fireEvent.keyDown(await within(header).findByRole("button", { name: "more" }), { key: "Enter" });
  fireEvent.click(await screen.findByRole("menuitem", { name: "detail.settings" }));

  expect(await screen.findByText("settings-editor")).toBeVisible();
  expect(screen.getByTestId("location").textContent).toBe("/filelib/7/settings?parent_id=9&fileStatus=abnormal&keep=1");
  expect(screen.getByTestId("settings-scope")).toHaveTextContent('"view":"ordinary"');
  expect(screen.queryByRole("complementary")).toBeNull();
  expect(screen.queryByRole("tab", { name: "f118.spaces" })).toBeNull();
  expect(screen.queryByTestId("files")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: action }));
  expect(await screen.findByTestId("files")).toHaveTextContent('"parent":9');
  expect(screen.getByTestId("location").textContent).toBe(directory);
});

it("redirects a legacy settings link to the standalone page and returns to its directory", async () => {
  mock.permissions.mockResolvedValue({ actions: ["edit"] });
  const directory = "/filelib/7?parent_id=9&fileStatus=abnormal&keep=1";
  mount(`${directory}&tab=settings`);
  expect(await screen.findByText("settings-editor")).toBeVisible();
  expect(screen.getByTestId("location").textContent).toBe("/filelib/7/settings?parent_id=9&fileStatus=abnormal&keep=1");
  fireEvent.click(screen.getByRole("button", { name: "back" }));
  expect(await screen.findByTestId("files")).toHaveTextContent('"parent":9');
  expect(screen.getByTestId("location").textContent).toBe(directory);
});

it("automatically opens the first sidebar space instead of rendering the ordinary space list", async () => {
  mount();
  expect(await screen.findByTestId("files")).toHaveTextContent('"id":7');
  expect(await screen.findByRole("heading", { name: "Reports" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "back" })).not.toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent("/filelib/7");
  expect(screen.queryByText("ordinary-list")).toBeNull();
});

it.each<Partial<User>>([
  { is_global_super: true },
  { is_child_admin: true },
  { web_menu: ["create_knowledge"] },
])("opens the dedicated creation page from the created group for a permitted user %j", async (user) => {
  mount("/filelib/7", user);
  const created = await screen.findByRole("region", { name: "sidebar.created" });
  const create = within(created).getByRole("button", { name: "f118.create_space" });
  expect(create).toBe(screen.getByRole("button", { name: "f118.create_space" }));
  fireEvent.click(create);
  expect(await screen.findByRole("heading", { name: "f118.create_space" })).toBeVisible();
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/filelib\/create$/);
  expect(screen.getByTestId("creation-scope")).toHaveTextContent(JSON.stringify(scope));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.queryByRole("region", { name: "sidebar.created" })).toBeNull();
});

it("does not show ordinary space creation for a user without creation access", async () => {
  mount("/filelib/7");
  expect(await screen.findByTestId("files")).toHaveTextContent('"view":"ordinary"');
  expect(screen.getByRole("region", { name: "sidebar.created" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "f118.create_space" })).toBeNull();
});

it("opens the creation page from an empty workspace and cancels back to it", async () => {
  const fallback = mock.get.getMockImplementation()!;
  mock.get.mockImplementation((url: string, options?: unknown) => {
    if (url.endsWith("/mine")) return Promise.resolve([]);
    if (url.endsWith("/space/list")) return Promise.resolve({ data: [], has_more: false });
    return fallback(url, options);
  });
  mount("/filelib", { web_menu: ["create_knowledge"] });
  await within(screen.getByRole("main")).findByText("sidebar.empty");
  fireEvent.click(screen.getByRole("button", { name: "f118.create_space" }));
  expect(await screen.findByRole("heading", { name: "f118.create_space" })).toBeVisible();
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/filelib\/create$/);

  fireEvent.click(screen.getByRole("button", { name: "cancel" }));
  await within(screen.getByRole("main")).findByText("sidebar.empty");
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/filelib$/);
});

it("cancels creation back to the original folder and filters", async () => {
  const folder = "/filelib/7?parent_id=9&fileStatus=abnormal";
  mount(folder, { is_child_admin: true });
  expect(await screen.findByTestId("files")).toHaveTextContent('"parent":9');
  fireEvent.click(screen.getByRole("button", { name: "f118.create_space" }));
  expect(await screen.findByRole("heading", { name: "f118.create_space" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "cancel" }));
  expect(await screen.findByTestId("files")).toHaveTextContent('"parent":9');
  expect(screen.getByTestId("location")).toHaveTextContent(folder);
});

it("redirects a user without creation access away from the dedicated route", async () => {
  mount("/filelib/create");
  expect(await screen.findByTestId("files")).toHaveTextContent('"view":"ordinary"');
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/filelib\/7$/);
  expect(screen.queryByRole("heading", { name: "f118.create_space" })).toBeNull();
});

it("cancels a direct creation link back to the ordinary workspace", async () => {
  mount("/filelib/create", { is_child_admin: true });
  expect(await screen.findByRole("heading", { name: "f118.create_space" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "cancel" }));
  expect(await screen.findByTestId("files")).toHaveTextContent('"view":"ordinary"');
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/filelib\/7$/);
});

it("shows the searchable management list without opening spaces or requesting their files", async () => {
  mount("/filelib?view=admin", { is_child_admin: true });
  fireEvent.click(await screen.findByText("Reports"));
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/filelib\?view=admin$/);
  const search = screen.getByRole("searchbox", { name: "sidebar.search" });
  fireEvent.change(search, { target: { value: "Repo" } });
  await waitFor(() => expect(mock.get).toHaveBeenCalledWith("/api/v1/knowledge/space/admin/list", {
    params: { page: 1, page_size: 20, keyword: "Repo" },
  }));
  expect(screen.queryByRole("complementary")).toBeNull();
  expect(screen.queryByTestId("files")).toBeNull();
  expect(mock.get.mock.calls.every(([url]) => String(url).endsWith("/admin/list"))).toBe(true);
  expect(screen.queryByRole("button", { name: "f118.create_space" })).toBeNull();
});

it("returns old management file and folder links to the list and keeps ordinary file browsing", async () => {
  mount("/filelib/7?view=admin&parent_id=9&file_id=21");
  expect(await screen.findByText("Reports")).toBeVisible();
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/filelib\?view=admin$/);
  expect(mock.get.mock.calls.every(([url]) => String(url).endsWith("/admin/list"))).toBe(true);
  fireEvent.mouseDown(screen.getByRole("tab", { name: "f118.spaces" }), { button: 0, ctrlKey: false });
  await waitFor(() => expect(screen.getByTestId("files")).toHaveTextContent('"view":"ordinary"'));
  expect(screen.getByTestId("location")).not.toHaveTextContent("view=admin");
});

it("opens standalone settings from the admin list", async () => {
  mock.permissions.mockResolvedValue({ actions: ["edit", "manage_permission", "delete"] });
  mount("/filelib?view=admin");
  const row = (await screen.findByText("Reports")).closest("tr")!;
  fireEvent.keyDown(within(row).getByRole("button", { name: "more" }), { key: "Enter" });
  const settings = await screen.findByRole("menuitem", { name: "detail.settings" });
  expect(screen.getByRole("menuitem", { name: "managePermission" })).toBeVisible();
  expect(screen.getByRole("menuitem", { name: "deletion.delete_space" })).toBeVisible();
  fireEvent.click(settings);
  expect(await screen.findByText("settings-editor")).toBeVisible();
  expect(screen.getByTestId("location").textContent).toBe("/filelib/7/settings?view=admin");
  expect(screen.getByTestId("settings-scope")).toHaveTextContent('"view":"admin"');
  expect(screen.queryByRole("tab", { name: "f118.manage_spaces" })).toBeNull();
  expect(screen.queryByTestId("files")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "back" }));
  expect(await screen.findByRole("table", { name: "f118.manage_spaces" })).toBeVisible();
  expect(screen.getByTestId("location").textContent).toBe("/filelib?view=admin");
});

it("opens metadata over the current admin list and keeps its search and focus on close", async () => {
  mock.permissions.mockResolvedValue({ actions: ["edit"] });
  mount("/filelib?view=admin");
  const table = await screen.findByRole("table", { name: "f118.manage_spaces" });
  const search = screen.getByRole("searchbox", { name: "sidebar.search" });
  fireEvent.change(search, { target: { value: "Repo" } });
  const row = (await within(table).findByText("Reports")).closest("tr")!;
  const more = within(row).getByRole("button", { name: "more" });
  fireEvent.keyDown(more, { key: "Enter" });
  fireEvent.click(await screen.findByRole("menuitem", { name: "detail.metadata" }));
  const metadata = await screen.findByRole("dialog", { name: "metaData" });
  expect(await within(metadata).findByText("document_id")).toBeVisible();
  expect(table).toBeVisible();
  expect(search).toHaveValue("Repo");
  expect(screen.getByTestId("location").textContent).toBe("/filelib?view=admin");
  fireEvent.click(within(metadata).getByRole("button", { name: /^close$/i }));
  await waitFor(() => expect(more).toHaveFocus());
  expect(screen.getByRole("table", { name: "f118.manage_spaces" })).toBe(table);
  expect(search).toHaveValue("Repo");
  expect(screen.getByTestId("location").textContent).toBe("/filelib?view=admin");
});

it("waits for earlier navigation groups before selecting the first space", async () => {
  let finish!: (rows: { id: number; name: string; tenant_id: number }[]) => void;
  const pending = new Promise<{ id: number; name: string; tenant_id: number }[]>((resolve) => { finish = resolve; });
  const fallback = mock.get.getMockImplementation()!;
  mock.get.mockImplementation((url: string, options?: unknown) => url.endsWith("/department") ? pending : fallback(url, options));
  mount();
  await screen.findByRole("button", { name: "Reports" });
  expect(screen.queryByTestId("files")).toBeNull();
  finish([{ id: 8, name: "Department first", tenant_id: 60 }]);
  await waitFor(() => expect(screen.getByTestId("files")).toHaveTextContent('"id":8'));
});

it("shows an empty workspace when no navigation or child-only space exists", async () => {
  const fallback = mock.get.getMockImplementation()!;
  mock.get.mockImplementation(async (url: string) => {
    if (url.endsWith("/mine")) return [];
    if (url.endsWith("/space/list")) return { data: [], has_more: false, next_cursor: null };
    return fallback(url);
  });
  mount();
  await waitFor(() => expect(mock.get).toHaveBeenCalledWith("/api/v1/knowledge/space/list", { params: { page_size: 1 } }));
  expect(screen.queryByTestId("files")).toBeNull();
  expect(screen.queryByText("ordinary-list")).toBeNull();
});

it("advances a child-only visible-space cursor without showing a space list", async () => {
  const fallback = mock.get.getMockImplementation()!;
  mock.get.mockImplementation(async (url: string, options?: { params?: { cursor?: string } }) => {
    if (url.endsWith("/mine") || url.endsWith("/department") || url.endsWith("/joined")) return [];
    if (url.endsWith("/list")) return options?.params?.cursor ? { data: [{ id: 12, name: "Child grant", tenant_id: 60 }], has_more: false } : { data: [], has_more: true, next_cursor: "opaque/+==" };
    return fallback(url, options);
  });
  mount();
  await waitFor(() => expect(screen.getByTestId("files")).toHaveTextContent('"id":12'));
  expect(mock.get).toHaveBeenCalledWith("/api/v1/knowledge/space/list", { params: { page_size: 1, cursor: "opaque/+==" } });
  expect(screen.queryByText("ordinary-list")).toBeNull();
});


it("does not let a late initial space redirect a user away from QA", async () => {
  let finish!: (value: object[]) => void;
  const delayed = new Promise<object[]>((resolve) => { finish = resolve; });
  const base = mock.get.getMockImplementation()!;
  mock.get.mockImplementation((url: string, options?: unknown) => url.endsWith("/department") ? delayed : base(url, options));
  mount();
  fireEvent.mouseDown(screen.getByRole("tab", { name: "lib.qaData" }), { button: 0, ctrlKey: false });
  await screen.findByText("qa-list");
  finish([{ id: 10, name: "Late department", tenant_id: 60 }]);
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/filelib?view=qa"));
  expect(screen.queryByTestId("files")).toBeNull();
});

it.each([
  "/filelib?view=admin",
  "/filelib/7/settings?view=admin&parent_id=9",
])("does not expose management reads through a forged URL %s", async (path) => {
  mock.scope.mockReturnValue({ scopes: { ordinary: scope }, canManage: false, isLoading: false, retry: vi.fn() });
  mount(path);
  await waitFor(() => expect(screen.getByTestId("files")).toHaveTextContent('"view":"ordinary"'));
  expect(screen.queryByText("settings-editor")).toBeNull();
  expect(screen.queryByRole("tab", { name: "f118.manage_spaces" })).toBeNull();
  expect(mock.get.mock.calls.some(([url]) => String(url).includes("/admin/list"))).toBe(false);
});

it("waits for a concrete management scope before reading spaces", () => {
  mock.scope.mockReturnValue({ scopes: undefined, canManage: true, isLoading: true, retry: vi.fn() });
  mount("/filelib?view=admin");
  expect(screen.getByText("f118.loading_space")).toBeVisible();
  expect(mock.get).not.toHaveBeenCalled();
});
