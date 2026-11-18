import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentProps } from "react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import KnowledgePage from "@/pages/KnowledgePage";
import { KnowledgeSpaceCreatePage } from "@/pages/KnowledgePage/KnowledgeSpaceCreatePage";
import { KnowledgeSpaceSettingsPage } from "@/pages/KnowledgePage/KnowledgeSpaceSettingsPage";
import { userContext } from "@/contexts/userContext";
import type { ProcessingJobRead } from "@/controllers/API/knowledgeSpace";
import type { FilesProps } from "@/pages/KnowledgePage/components/Files";
import type { CreateSpaceForm } from "@/pages/KnowledgePage/components/KnowledgeLibraryDialog";
import type { SpaceSettingsEditor } from "@/pages/KnowledgePage/components/SpaceSettingsEditor";
import type { SpaceFileDetail } from "@/pages/KnowledgePage/components/SpaceFileDetail";
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
vi.mock("@/pages/KnowledgePage/components/Files", () => ({ default: (props: FilesProps) => <output data-testid="files">{JSON.stringify({ id: props.spaceId, parent: props.parentId, presentation: props.presentation, view: props.scope?.view, scope: props.scope })}</output> }));
vi.mock("@/pages/KnowledgePage/components/SpaceFileDetail", () => ({
  SpaceFileDetail: ({ scope: fileScope, spaceId, fileId, onBack }: ComponentProps<typeof SpaceFileDetail>) => (
    <section>
      <output data-testid="file-detail">{JSON.stringify({ scope: fileScope, spaceId, fileId })}</output>
      <button onClick={onBack}>file-back</button>
    </section>
  ),
}));

const scope = { identityKey: "user:5", tenantId: 60, managementTenantId: 60, view: "ordinary" } as const;
const taskKinds = ["embedding_rebuild", "move_index"] as const;
const jobsPath = "/api/v1/knowledge/space/7/processing-jobs";
type TaskKind = (typeof taskKinds)[number];
const clients: QueryClient[] = [];
function Location() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><output data-testid="location">{location.pathname}{location.search}</output><button onClick={() => navigate(-1)}>history-back</button><button onClick={() => navigate(1)}>history-forward</button></>;
}
function mount(path = "/filelib", user: Partial<User> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const view = render(
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
  return { ...view, client };
}

function mockTaskRecords(kinds: readonly TaskKind[]) {
  const jobs: ProcessingJobRead[] = kinds.map((kind) => ({
    id: `job-${kind}`,
    space_id: 7,
    kind,
    state: "succeeded",
    revision: 1,
    accepted_at: "2026-11-17T09:00:00",
    started_at: null,
    finished_at: null,
    total_count: 1,
    succeeded_count: 1,
    failed_count: 0,
    pending_count: 0,
    hidden_item_count: 0,
    retryable: false,
    error_code: null,
    obsolete_reason: null,
  }));
  const read = mock.get.getMockImplementation()!;
  mock.get.mockImplementation(async (url: string, options?: { params?: { kind?: string } }) => {
    if (url === jobsPath) {
      const data = jobs.filter(({ kind }) => kind === options?.params?.kind);
      return { data, total: data.length };
    }
    if (url.startsWith(`${jobsPath}/`) && url.endsWith("/items")) return { data: [], total: 0 };
    const job = jobs.find(({ id }) => url === `${jobsPath}/${id}`);
    return job ?? read(url, options);
  });
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
  expect(await screen.findByTestId("files")).toHaveTextContent('"view":"admin"');
  expect(screen.getByRole("complementary")).toBeVisible();
  expect(screen.getByRole("region", { name: "sidebar.personal" })).toBeVisible();
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

it("hides task records when both histories are empty", async () => {
  mock.permissions.mockResolvedValue({ actions: ["edit"] });
  const { client } = mount("/filelib/7");
  await screen.findByRole("heading", { name: "Reports" });
  await waitFor(() => {
    for (const kind of taskKinds) {
      expect(mock.get).toHaveBeenCalledWith(jobsPath, {
        params: expect.objectContaining({ kind }),
      });
    }
    expect(client.isFetching()).toBe(0);
  });
  expect(screen.queryByRole("button", { name: "detail.task_records" })).not.toBeInTheDocument();
});

it.each(taskKinds)("shows the root header entry when only %s has records and hides it in folders", async (kind) => {
  mock.permissions.mockResolvedValue({ actions: ["edit"] });
  mockTaskRecords([kind]);
  mount("/filelib/7");
  const title = await screen.findByRole("heading", { name: "Reports" });
  const entry = await within(title.closest("header")!).findByRole("button", { name: "detail.task_records" });
  expect(title.compareDocumentPosition(entry) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

  const sidebar = within(screen.getByRole("complementary"));
  fireEvent.click(await sidebar.findByRole("button", { name: "Finance" }));
  await screen.findByRole("navigation", { name: "f118.current_folder" });
  expect(screen.queryByRole("button", { name: "detail.task_records" })).not.toBeInTheDocument();

  fireEvent.click(await within(screen.getByRole("navigation", { name: "f118.current_folder" })).findByRole("button", { name: "Reports" }));
  expect(await screen.findByRole("button", { name: "detail.task_records" })).toBeVisible();
});

it("opens both histories and their job details from a single dialog", async () => {
  mock.permissions.mockResolvedValue({ actions: ["edit"] });
  mockTaskRecords(taskKinds);
  mount("/filelib/7");
  const interaction = userEvent.setup();
  const entry = await screen.findByRole("button", { name: "detail.task_records" });
  await interaction.click(entry);
  const dialog = within(await screen.findByRole("dialog", { name: "detail.task_records" }));
  expect(dialog.getByRole("tab", { name: "f118.processing_title_jobs" })).toHaveAttribute("aria-selected", "true");
  await interaction.click(await dialog.findByRole("button", { name: "f118.processing_kind_embedding_rebuild · f118.processing_state_succeeded" }));
  expect(await dialog.findByText("f118.processing_counts")).toBeVisible();
  expect(mock.get).toHaveBeenCalledWith(`${jobsPath}/job-embedding_rebuild`, expect.any(Object));
  await interaction.click(dialog.getByRole("button", { name: "detail.back_to_jobs" }));

  await interaction.click(dialog.getByRole("tab", { name: "move.jobs" }));
  await interaction.click(await dialog.findByRole("button", { name: "move.jobs · f118.processing_state_succeeded" }));
  expect(await dialog.findByText("f118.processing_counts")).toBeVisible();
  expect(mock.get).toHaveBeenCalledWith(`${jobsPath}/job-move_index`, { params: { kind: "move_index" } });

  await interaction.keyboard("{Escape}");
  expect(screen.queryByRole("dialog", { name: "detail.task_records" })).not.toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/filelib\/7$/);
});

it("opens permitted move records without requesting processing history for a non-editor", async () => {
  mock.permissions.mockResolvedValue({ actions: ["visible"] });
  mockTaskRecords(["move_index"]);
  mount("/filelib/7");
  fireEvent.click(await screen.findByRole("button", { name: "detail.task_records" }));
  const dialog = within(await screen.findByRole("dialog", { name: "detail.task_records" }));
  expect(await dialog.findByRole("button", { name: "move.jobs · f118.processing_state_succeeded" })).toBeVisible();
  expect(mock.get).not.toHaveBeenCalledWith(jobsPath, {
    params: expect.objectContaining({ kind: "embedding_rebuild" }),
  });
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

it("pages and searches all managed spaces within department and personal groups", async () => {
  const fallback = mock.get.getMockImplementation()!;
  mock.get.mockImplementation(async (url: string, options?: { params?: { page?: number; keyword?: string } }) => {
    if (!url.endsWith("/admin/list")) return fallback(url, options);
    if (options?.params?.keyword) return { data: [{ id: 12, name: "Later personal", tenant_id: 60, space_kind: "normal" }], total: 1 };
    if (options?.params?.page === 2) return { data: [{ id: 12, name: "Later personal", tenant_id: 60, space_kind: "normal" }], total: 201 };
    return {
      data: [
        { id: 7, name: "Personal reports", tenant_id: 60, space_kind: "normal" },
        { id: 8, name: "Department reports", tenant_id: 60, space_kind: "department" },
      ],
      total: 201,
    };
  });
  mount("/filelib?view=admin", { is_child_admin: true });
  const files = await screen.findByTestId("files");
  expect(files).toHaveTextContent('"id":8');
  expect(files).toHaveTextContent('"scope":{"identityKey":"user:5","tenantId":60,"managementTenantId":60,"view":"admin"}');
  expect(screen.getByTestId("location").textContent).toBe("/filelib/8?view=admin");
  const sidebar = within(screen.getByRole("complementary"));
  expect(sidebar.getByRole("region", { name: "sidebar.department" })).toHaveTextContent("Department reports");
  expect(sidebar.getByRole("region", { name: "sidebar.personal" })).toHaveTextContent("Personal reports");
  expect(sidebar.queryByRole("region", { name: "sidebar.created" })).toBeNull();
  expect(sidebar.queryByRole("region", { name: "sidebar.joined" })).toBeNull();
  expect(sidebar.queryByRole("button", { name: "f118.create_space" })).toBeNull();
  fireEvent.click(sidebar.getByRole("button", { name: "sidebar.more_spaces" }));
  expect(await sidebar.findByRole("button", { name: "Later personal" })).toBeVisible();
  expect(mock.get).toHaveBeenCalledWith("/api/v1/knowledge/space/admin/list", {
    params: { page: 2, page_size: 200 },
  });

  const search = sidebar.getByRole("searchbox", { name: "sidebar.search" });
  fireEvent.change(search, { target: { value: "Later" } });
  await waitFor(() => expect(mock.get).toHaveBeenCalledWith("/api/v1/knowledge/space/admin/list", {
    params: { page: 1, page_size: 200, keyword: "Later" },
  }));
  await waitFor(() => expect(sidebar.queryByRole("button", { name: "Department reports" })).toBeNull());
  expect(await sidebar.findByRole("button", { name: "Later personal" })).toBeVisible();
  expect(screen.getByTestId("files")).toBe(files);
  expect(screen.getByTestId("location").textContent).toBe("/filelib/8?view=admin");
  fireEvent.change(search, { target: { value: "" } });
  expect(await sidebar.findByRole("button", { name: "Department reports" })).toBeVisible();
  expect(mock.get.mock.calls.some(([url]) => /\/(?:mine|joined|department)$/.test(url) || url.endsWith("/space/list"))).toBe(false);
});

it("opens management folder and file links with their original scope and filters", async () => {
  const directory = "/filelib/7?view=admin&parent_id=9&fileStatus=abnormal&keep=1";
  mount(`${directory}&file_id=21`);
  const file = await screen.findByTestId("file-detail");
  expect(file).toHaveTextContent('"spaceId":7,"fileId":21');
  expect(file).toHaveTextContent('"view":"admin"');
  expect(screen.getByTestId("location").textContent).toBe(`${directory}&file_id=21`);
  fireEvent.click(screen.getByRole("button", { name: "file-back" }));
  expect(await screen.findByTestId("files")).toHaveTextContent('"parent":9');
  expect(screen.getByTestId("files")).toHaveTextContent('"view":"admin"');
  expect(screen.getByTestId("location").textContent).toBe(directory);
  fireEvent.mouseDown(screen.getByRole("tab", { name: "f118.spaces" }), { button: 0, ctrlKey: false });
  expect(await screen.findByTestId("files")).toHaveTextContent('"view":"ordinary"');
  expect(screen.getByTestId("location")).not.toHaveTextContent("view=admin");
});

it.each(["back", "cancel", "confirm"])("returns from management settings to the same folder on %s", async (action) => {
  mock.permissions.mockResolvedValue({ actions: ["edit", "manage_permission", "delete"] });
  const directory = "/filelib/7?view=admin&parent_id=9&fileStatus=abnormal&keep=1";
  mount(directory);
  const header = (await screen.findByRole("navigation", { name: "f118.current_folder" })).closest("header")!;
  fireEvent.keyDown(await within(header).findByRole("button", { name: "more" }), { key: "Enter" });
  const settings = await screen.findByRole("menuitem", { name: "detail.settings" });
  expect(screen.getByRole("menuitem", { name: "managePermission" })).toBeVisible();
  expect(screen.getByRole("menuitem", { name: "deletion.delete_space" })).toBeVisible();
  fireEvent.click(settings);
  expect(await screen.findByText("settings-editor")).toBeVisible();
  expect(screen.getByTestId("location").textContent).toBe("/filelib/7/settings?view=admin&parent_id=9&fileStatus=abnormal&keep=1");
  expect(screen.getByTestId("settings-scope")).toHaveTextContent('"view":"admin"');
  expect(screen.queryByRole("tab", { name: "f118.manage_spaces" })).toBeNull();
  expect(screen.queryByTestId("files")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: action }));
  expect(await screen.findByTestId("files")).toHaveTextContent('"view":"admin"');
  expect(screen.getByTestId("files")).toHaveTextContent('"parent":9');
  expect(screen.getByTestId("location").textContent).toBe(directory);
});

it("opens metadata over the managed files and keeps sidebar search and focus on close", async () => {
  mock.permissions.mockResolvedValue({ actions: ["edit"] });
  mount("/filelib?view=admin");
  const files = await screen.findByTestId("files");
  const search = within(screen.getByRole("complementary")).getByRole("searchbox", { name: "sidebar.search" });
  fireEvent.change(search, { target: { value: "Repo" } });
  const header = (await screen.findByRole("heading", { name: "Reports" })).closest("header")!;
  const more = await within(header).findByRole("button", { name: "more" });
  fireEvent.keyDown(more, { key: "Enter" });
  fireEvent.click(await screen.findByRole("menuitem", { name: "detail.metadata" }));
  const metadata = await screen.findByRole("dialog", { name: "metaData" });
  expect(await within(metadata).findByText("document_id")).toBeVisible();
  expect(files).toBeVisible();
  expect(search).toHaveValue("Repo");
  expect(screen.getByTestId("location").textContent).toBe("/filelib/7?view=admin");
  fireEvent.click(within(metadata).getByRole("button", { name: /^close$/i }));
  await waitFor(() => expect(more).toHaveFocus());
  expect(screen.getByTestId("files")).toBe(files);
  expect(search).toHaveValue("Repo");
  expect(screen.getByTestId("location").textContent).toBe("/filelib/7?view=admin");
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
