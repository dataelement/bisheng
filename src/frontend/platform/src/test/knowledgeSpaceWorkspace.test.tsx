import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import KnowledgePage from "@/pages/KnowledgePage";
import { userContext } from "@/contexts/userContext";
import type { FilesProps } from "@/pages/KnowledgePage/components/Files";

const mock = vi.hoisted(() => ({ get: vi.fn(), scope: vi.fn() }));
vi.mock("@/contexts/userContext", async () => ({ userContext: (await import("react")).createContext({ user: {} }) }));
vi.mock("@/hooks/useKnowledgePageScope", () => ({ useKnowledgePageScope: mock.scope }));
vi.mock("@/controllers/API/permission", () => ({ getMyResourcePermissionsApi: async () => ({ actions: [] }) }));
vi.mock("@/controllers/request", () => ({ default: { get: mock.get }, showApiError: vi.fn() }));
vi.mock("@/pages/KnowledgePage/KnowledgeQa", () => ({ default: () => <p>qa-list</p> }));
vi.mock("@/pages/KnowledgePage/components/KnowledgeLibraryDialog", () => ({ KnowledgeLibraryDialog: () => null }));
vi.mock("@/pages/KnowledgePage/components/Files", () => ({ default: (props: FilesProps) => <output data-testid="files">{JSON.stringify({ id: props.spaceId, parent: props.parentId, presentation: props.presentation, view: props.scope?.view })}</output> }));

const scope = { identityKey: "user:5", tenantId: 60, managementTenantId: 60, view: "ordinary" } as const;
const clients: QueryClient[] = [];
function Location() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><output data-testid="location">{location.pathname}{location.search}</output><button onClick={() => navigate(-1)}>history-back</button><button onClick={() => navigate(1)}>history-forward</button></>;
}
function mount(path = "/filelib") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  return render(<QueryClientProvider client={client}><userContext.Provider value={{ user: { user_id: 5 }, setUser: vi.fn(), savedComponents: [], addSavedComponent: async () => undefined, checkComponentsName: () => false, delComponent: vi.fn() }}><MemoryRouter initialEntries={[path]}><Location /><Routes><Route path="/filelib" element={<KnowledgePage />} /><Route path="/filelib/:id" element={<KnowledgePage />} /></Routes></MemoryRouter></userContext.Provider></QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  mock.scope.mockReturnValue({ scopes: { ordinary: scope, admin: { ...scope, view: "admin" } }, canManage: true, isLoading: false, retry: vi.fn() });
  mock.get.mockImplementation(async (url: string, options?: { params?: { file_type?: number; parent_id?: number | null } }) => {
    if (url.endsWith("/admin/list")) return { data: [{ id: 7, name: "Reports", tenant_id: 60, space_kind: "normal" }], total: 1 };
    if (url.endsWith("/mine")) return [{ id: 7, name: "Reports", tenant_id: 60 }];
    if (url.endsWith("/joined") || url.endsWith("/department")) return [];
    if (url.endsWith("/children") && options?.params?.file_type === 0) return { data: options.params.parent_id == null ? [{ id: 9, file_name: "Finance", file_type: 0 }] : [], has_more: false, next_cursor: null };
    if (url.endsWith("/info")) return { id: 7, name: "Reports", description: "Latest reports" };
    if (url.endsWith("/parent")) return [{ id: 9, file_name: "Finance" }];
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
  fireEvent.mouseDown(screen.getByRole("tab", { name: "lib.qaData" }), { button: 0, ctrlKey: false });
  expect(await screen.findByText("qa-list")).toBeVisible();
  fireEvent.mouseDown(screen.getByRole("tab", { name: "f118.manage_spaces" }), { button: 0, ctrlKey: false });
  await waitFor(() => expect(screen.getByTestId("files")).toHaveTextContent('"view":"admin"'));
  expect(screen.getByRole("complementary")).toBeVisible();
});

it("rejects invalid directory links without loading their file content", async () => {
  mount("/filelib/7?parent_id=9&parent_id=10");
  expect(screen.getByText("f118.scope_unavailable")).toBeVisible();
  expect(screen.queryByTestId("files")).toBeNull();
  await screen.findByRole("button", { name: "Reports" });
  expect(mock.get.mock.calls.some(([url]) => String(url).endsWith("/info"))).toBe(false);
});

it("selects file content from a configuration deep link while retaining directory filters", async () => {
  mount("/filelib/7?tab=embedding&fileStatus=abnormal&keep=1");
  const tree = screen.getByRole("complementary");
  fireEvent.click(await within(tree).findByRole("button", { name: "Finance" }));
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/filelib/7?fileStatus=abnormal&keep=1&parent_id=9"));
  expect(screen.getByTestId("location")).not.toHaveTextContent("tab=");
});

it("automatically opens the first sidebar space instead of rendering the ordinary space list", async () => {
  mount();
  expect(await screen.findByTestId("files")).toHaveTextContent('"id":7');
  expect(await screen.findByRole("heading", { name: "Reports" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "back" })).not.toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent("/filelib/7");
  expect(screen.queryByText("ordinary-list")).toBeNull();
});

it("opens management defaults with two groups and never loads ordinary navigation", async () => {
  mount("/filelib?view=admin");
  expect(await screen.findByTestId("files")).toHaveTextContent('"view":"admin"');
  expect(screen.getByTestId("location")).toHaveTextContent("/filelib/7?view=admin");
  const tree = screen.getByRole("complementary");
  expect(within(tree).getByRole("region", { name: "sidebar.department" })).toBeVisible();
  expect(within(tree).getByRole("region", { name: "sidebar.personal" })).toBeVisible();
  expect(within(tree).queryByRole("region", { name: "sidebar.created" })).toBeNull();
  expect(within(tree).getByRole("searchbox", { name: "sidebar.search" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "back" })).toBeNull();
  expect(mock.get.mock.calls.some(([url]) => /\/(department|mine|joined)$/.test(String(url)))).toBe(false);
  expect(screen.queryByRole("button", { name: "f118.create_space" })).toBeNull();
});

it("preserves admin scope while selecting a folder and switching to ordinary navigation", async () => {
  mount("/filelib/7?view=admin");
  await screen.findByTestId("files");
  fireEvent.click(await within(screen.getByRole("complementary")).findByRole("button", { name: "Finance" }));
  await waitFor(() => expect(screen.getByTestId("files")).toHaveTextContent('"parent":9'));
  expect(screen.getByTestId("location")).toHaveTextContent("view=admin&parent_id=9");
  fireEvent.mouseDown(screen.getByRole("tab", { name: "f118.spaces" }), { button: 0, ctrlKey: false });
  await waitFor(() => expect(screen.getByTestId("files")).toHaveTextContent('"view":"ordinary"'));
  expect(screen.getByTestId("location")).not.toHaveTextContent("view=admin");
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
  mock.get.mockResolvedValue([]);
  mock.get.mockImplementation(async (url: string) => url.endsWith("/list") ? { data: [], has_more: false, next_cursor: null } : []);
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

it("does not expose management reads through a forged URL", async () => {
  mock.scope.mockReturnValue({ scopes: { ordinary: scope }, canManage: false, isLoading: false, retry: vi.fn() });
  mount("/filelib?view=admin");
  await waitFor(() => expect(screen.getByTestId("files")).toHaveTextContent('"view":"ordinary"'));
  expect(screen.queryByRole("tab", { name: "f118.manage_spaces" })).toBeNull();
  expect(mock.get.mock.calls.some(([url]) => String(url).includes("/admin/list"))).toBe(false);
});

it("waits for a concrete management scope before reading spaces", () => {
  mock.scope.mockReturnValue({ scopes: undefined, canManage: true, isLoading: true, retry: vi.fn() });
  mount("/filelib?view=admin");
  expect(screen.getByText("f118.loading_space")).toBeVisible();
  expect(mock.get).not.toHaveBeenCalled();
});
