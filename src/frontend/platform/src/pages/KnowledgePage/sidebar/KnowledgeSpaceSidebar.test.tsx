import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { KnowledgeSpaceSidebar, type KnowledgeSpaceSidebarProps } from "./KnowledgeSpaceSidebar";

const mocks = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), children: vi.fn(), parents: vi.fn(), error: vi.fn(), copies: vi.fn(),
}));
vi.mock("../hooks/useSpaceActions", () => ({ useSpaceActions: () => ({ load: vi.fn(), render: () => null, dialogs: null }) }));
vi.mock("@/controllers/API/knowledgeCopy", () => ({ listOwnedSpaceCopies: mocks.copies }));
vi.mock("@/controllers/request", () => ({ default: { get: mocks.get, post: mocks.post }, showApiError: mocks.error }));
vi.mock("@/controllers/API/knowledgeSpace", () => ({ knowledgeSpaceApi: { listChildren: mocks.children, listAdminSpaces: (query: object) => mocks.get("/api/v1/knowledge/space/admin/list", { params: query }), listVisibleSpaces: (query: object) => mocks.get("/api/v1/knowledge/space/list", { params: query }) } }));
vi.mock("@/controllers/API/knowledgeFiles", () => ({ knowledgeFilesApi: { listSpaceFolderParents: mocks.parents } }));
vi.mock("@/controllers/hooks/knowledge", () => ({
  knowledgeQueryKeys: {
    scope: (scope: { identityKey: string; tenantId: number; managementTenantId: number | null; view: string }) => ["f118-knowledge", scope.identityKey, scope.tenantId, scope.managementTenantId, scope.view],
    space: (scope: { identityKey: string; tenantId: number; managementTenantId: number | null; view: string }, id: number) => ["f118-knowledge", scope.identityKey, scope.tenantId, scope.managementTenantId, scope.view, "space", id],
  },
}));

const scope = { identityKey: "user:2", tenantId: 60, managementTenantId: 60, view: "ordinary" as const };
const page = (data: { id: number; knowledge_id: number; file_name: string; file_type: number }[], hasMore = false, cursor: string | null = null) => ({ data, page_size: 100, has_more: hasMore, next_cursor: cursor });
const folder = (id: number, name: string) => ({ id, knowledge_id: 7, file_name: name, file_type: 0 });
const clients: QueryClient[] = [];
function setup(extra: Partial<KnowledgeSpaceSidebarProps> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const props = { scope, canCopy: true, onSelect: vi.fn(), ...extra };
  const draw = (next = props) => <QueryClientProvider client={client}><KnowledgeSpaceSidebar {...next} /></QueryClientProvider>;
  return { props, draw, client };
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.copies.mockResolvedValue([]);
  mocks.get.mockImplementation((url: string) => Promise.resolve(url.endsWith("/mine") ? [{ id: 7, name: "My space", is_pinned: false }] : []));
  mocks.post.mockResolvedValue(true);
  mocks.children.mockResolvedValue(page([]));
  mocks.parents.mockResolvedValue([]);
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

it("discovers unfinished copies after refresh and keeps their contents closed", async () => {
  mocks.copies.mockResolvedValue([{ id: 88, name: "New copy", user_id: 2, state: 0, job_id: "copy-job", job_state: "accepted", phase: "initializing", total_count: 10, succeeded_count: 0, failed_count: 0 }]);
  const f = setup();
  render(f.draw());
  fireEvent.click(await screen.findByRole("button", { name: /New copy/ }));
  expect(f.props.onSelect).toHaveBeenCalledWith(88, null);
  expect(screen.getAllByRole("status").some((node) => node.textContent === "space_copy_ui.in_progress")).toBe(true);
  expect(screen.queryByRole("button", { name: "sidebar.expand New copy" })).toBeNull();
  expect(mocks.children).not.toHaveBeenCalled();
  mocks.copies.mockResolvedValue([{ id: 88, name: "New copy", user_id: 2, state: 0, job_id: "copy-job", job_state: "failed", phase: "failed", total_count: 10, succeeded_count: 0, failed_count: 10 }]);
  await act(() => f.client.invalidateQueries({ queryKey: ["f118-knowledge", "user:2", 60, 60, "ordinary", "copy-tasks"] }));
  await waitFor(() => expect(screen.getAllByRole("status").some((node) => node.textContent === "space_copy_ui.failed")).toBe(true));
});

it("preserves the three groups and only loads folders when their space is expanded", async () => {
  mocks.children.mockResolvedValueOnce(page([folder(9, "Root folder"), { ...folder(10, "Not a folder"), file_type: 1 }]));
  const f = setup();
  render(f.draw());
  await screen.findByRole("button", { name: "My space" });
  expect(mocks.get).toHaveBeenCalledWith("/api/v1/knowledge/space/department", { params: { order_by: "update_time" } });
  expect(mocks.get).toHaveBeenCalledWith("/api/v1/knowledge/space/joined", { params: { order_by: "update_time" } });
  expect(mocks.children).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "sidebar.expand My space" }));
  fireEvent.click(await screen.findByRole("button", { name: "Root folder" }));
  expect(f.props.onSelect).toHaveBeenCalledWith(7, 9);
  expect(mocks.children).toHaveBeenCalledExactlyOnceWith(7, { parent_id: null, file_type: 0, page_size: 100 });
  expect(screen.queryByText("Not a folder")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "sidebar.expand Root folder" }));
  await waitFor(() => expect(mocks.children).toHaveBeenLastCalledWith(7, { parent_id: 9, file_type: 0, page_size: 100 }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "sidebar.collapse Root folder" })).toBeNull());
  expect(screen.getByRole("button", { name: "Root folder" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "f118.create_space" })).toBeNull();
});

it("advances an empty cursor page and does not truncate the folder tree", async () => {
  mocks.children.mockResolvedValueOnce(page([], true, "opaque/+==")).mockResolvedValueOnce(page([folder(11, "Later folder")]));
  const f = setup();
  render(f.draw());
  fireEvent.click(await screen.findByRole("button", { name: "sidebar.expand My space" }));
  fireEvent.click(await screen.findByRole("button", { name: "sidebar.more_folders" }));
  await screen.findByRole("button", { name: "Later folder" });
  expect(mocks.children).toHaveBeenLastCalledWith(7, { parent_id: null, file_type: 0, page_size: 100, cursor: "opaque/+==" });
});

it("resizes the sidebar without losing expanded folders or fetching them again", async () => {
  mocks.children.mockResolvedValue(page([folder(9, "Root folder")]));
  const f = setup();
  render(f.draw());
  fireEvent.click(await screen.findByRole("button", { name: "sidebar.expand My space" }));
  await screen.findByRole("button", { name: "Root folder" });
  const reads = mocks.children.mock.calls.length;
  const handle = screen.getByRole("separator", { name: "sidebar.resize_navigation" });
  const sidebar = screen.getByRole("complementary");
  try {
    fireEvent.keyDown(handle, { key: "Home" });
    expect(sidebar).toHaveStyle({ width: "200px" });
    expect(screen.getByRole("button", { name: "Root folder" })).toBeVisible();
    fireEvent.keyDown(handle, { key: "End" });
    expect(sidebar).toHaveStyle({ width: "480px" });
    expect(screen.getByRole("button", { name: "Root folder" })).toBeVisible();
  } finally {
    fireEvent.doubleClick(handle);
  }
  expect(sidebar).toHaveStyle({ width: "240px" });
  expect(mocks.children).toHaveBeenCalledTimes(reads);
});

it("selects without expanding and restores nested expansion when a group reopens", async () => {
  mocks.children.mockImplementation((_space: number, query: { parent_id: number | null }) => Promise.resolve(
    query.parent_id === null ? page([folder(9, "Root folder")]) : page([folder(12, "Nested folder")]),
  ));
  const f = setup();
  const view = render(f.draw());

  fireEvent.click(await screen.findByRole("button", { name: "My space" }));
  expect(f.props.onSelect).toHaveBeenCalledWith(7, null);
  view.rerender(f.draw({ ...f.props, spaceId: 7 }));
  expect(screen.getByRole("button", { name: "My space" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("button", { name: "sidebar.expand My space" })).toHaveAttribute("aria-expanded", "false");
  expect(mocks.children).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "sidebar.expand My space" }));
  fireEvent.click(await screen.findByRole("button", { name: "sidebar.expand Root folder" }));
  await screen.findByRole("button", { name: "Nested folder" });
  fireEvent.click(screen.getByRole("button", { name: "sidebar.created" }));
  expect(screen.queryByRole("button", { name: "Nested folder" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "sidebar.created" }));
  expect(await screen.findByRole("button", { name: "Nested folder" })).toBeVisible();
});

it("restores a deep-linked folder through paginated ancestors", async () => {
  mocks.parents.mockResolvedValue([{ id: 9, file_name: "Root folder" }, { id: 12, file_name: "Selected folder" }]);
  mocks.children.mockImplementation((_space: number, query: { parent_id: number | null; cursor?: string }) => Promise.resolve(
    query.parent_id === null
      ? query.cursor ? page([folder(9, "Root folder")]) : page([], true, "later")
      : query.parent_id === 9 ? page([folder(12, "Selected folder")]) : page([]),
  ));
  const f = setup({ spaceId: 7, parentId: 12 });
  render(f.draw());
  const selected = await screen.findByRole("button", { name: "Selected folder" });
  expect(selected).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("button", { name: "sidebar.expand Selected folder" })).toHaveAttribute("aria-expanded", "false");
  expect(mocks.children).toHaveBeenCalledWith(7, { parent_id: null, file_type: 0, page_size: 100, cursor: "later" });
  expect(mocks.parents).toHaveBeenCalledWith(7, 12, expect.any(AbortSignal));
});

it("sorts only the selected group and pins through the existing API contract", async () => {
  const f = setup();
  render(f.draw());
  await screen.findByRole("button", { name: "My space" });
  fireEvent.keyDown(screen.getByRole("button", { name: "sidebar.sort sidebar.created" }), { key: "Enter" });
  fireEvent.click(await screen.findByRole("menuitemcheckbox", { name: "sidebar.sort_name" }));
  await waitFor(() => expect(mocks.get).toHaveBeenCalledWith("/api/v1/knowledge/space/mine", { params: { order_by: "name" } }));
  expect(mocks.get).not.toHaveBeenCalledWith("/api/v1/knowledge/space/joined", { params: { order_by: "name" } });
  fireEvent.keyDown(await screen.findByRole("button", { name: "more My space" }), { key: "Enter" });
  fireEvent.click(await screen.findByRole("menuitem", { name: "sidebar.pin" }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/v1/knowledge/space/7/set-pin", { is_pined: true }));
});

it("retires a pending old tenant response and its create control on scope change", async () => {
  let resolveOld: (value: { id: number; name: string }[]) => void = () => {};
  const old = new Promise<{ id: number; name: string }[]>((resolve) => { resolveOld = resolve; });
  mocks.get.mockImplementation((url: string) => url.endsWith("/mine") ? old : Promise.resolve([]));
  const f = setup();
  const view = render(f.draw());
  await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(3));
  mocks.get.mockImplementation((url: string) => Promise.resolve(url.endsWith("/mine") ? [{ id: 8, name: "New tenant" }] : []));
  view.rerender(f.draw({ ...f.props, canCopy: false, scope: { ...scope, tenantId: 202, managementTenantId: 202 } }));
  await screen.findByRole("button", { name: "New tenant" });
  await act(async () => resolveOld([{ id: 7, name: "Old tenant" }]));
  expect(screen.queryByText("Old tenant")).toBeNull();
  expect(screen.queryByRole("button", { name: "f118.create_space" })).toBeNull();
});

it("shows a retry when folder loading fails and retains the expansion", async () => {
  mocks.children.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(page([folder(9, "Recovered folder")]));
  const f = setup();
  render(f.draw());
  fireEvent.click(await screen.findByRole("button", { name: "sidebar.expand My space" }));
  fireEvent.click(await screen.findByRole("button", { name: "retry" }));
  await screen.findByRole("button", { name: "Recovered folder" });
});

it("does not issue navigation reads without a concrete tenant scope", () => {
  const f = setup({ scope: { ...scope, tenantId: 0 } });
  render(f.draw());
  expect(screen.getByRole("status")).toHaveTextContent("f118.scope_unavailable");
  expect(mocks.get).not.toHaveBeenCalled();
  expect(mocks.parents).not.toHaveBeenCalled();
});

it("ignores a retired A response after switching A -> B -> A and filters another tenant's rows", async () => {
  let resolveOld: (value: { id: number; name: string }[]) => void = () => {};
  const old = new Promise<{ id: number; name: string }[]>((resolve) => { resolveOld = resolve; });
  mocks.get.mockImplementation((url: string) => url.endsWith("/mine") ? old : Promise.resolve([]));
  const f = setup();
  const view = render(f.draw());
  await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(3));
  mocks.get.mockImplementation((url: string) => Promise.resolve(url.endsWith("/mine") ? [{ id: 8, name: "Tenant B", tenant_id: 202 }] : []));
  view.rerender(f.draw({ ...f.props, scope: { ...scope, tenantId: 202, managementTenantId: 202 } }));
  await screen.findByRole("button", { name: "Tenant B" });
  mocks.get.mockImplementation((url: string) => Promise.resolve(url.endsWith("/mine") ? [{ id: 9, name: "New tenant A", tenant_id: 60 }, { id: 8, name: "Wrong tenant", tenant_id: 202 }] : []));
  view.rerender(f.draw());
  await screen.findByRole("button", { name: "New tenant A" });
  await act(async () => resolveOld([{ id: 7, name: "Retired tenant A" }]));
  expect(screen.queryByText("Retired tenant A")).toBeNull();
  expect(screen.queryByText("Wrong tenant")).toBeNull();
});

it("stops automatic deep-link paging after a failure and retries the same opaque cursor", async () => {
  mocks.parents.mockResolvedValue([{ id: 12, file_name: "Selected folder" }]);
  mocks.children.mockResolvedValueOnce(page([], true, "later/+=="))
    .mockRejectedValueOnce(new Error("next page offline"))
    .mockResolvedValueOnce(page([folder(12, "Selected folder")]))
    .mockResolvedValue(page([]));
  const f = setup({ spaceId: 7, parentId: 12 });
  render(f.draw());
  const retry = await screen.findByRole("button", { name: "retry" });
  expect(mocks.children).toHaveBeenCalledTimes(2);
  fireEvent.click(retry);
  await screen.findByRole("button", { name: "Selected folder" });
  expect(mocks.children).toHaveBeenNthCalledWith(3, 7, { parent_id: null, file_type: 0, page_size: 100, cursor: "later/+==" });
});


it("pages management spaces into department and personal groups without ordinary navigation or creation", async () => {
  mocks.get.mockImplementation(async (_url: string, options: { params: { page?: number; keyword?: string } }) => options.params.page === 2
    ? { data: [{ id: 9, name: "Later personal", space_kind: "normal" }], total: 201 }
    : { data: [{ id: 7, name: "Department", space_kind: "department" }, { id: 8, name: "Personal", space_kind: "normal" }], total: 201 });
  const f = setup({ scope: { ...scope, view: "admin" as const } });
  render(f.draw());
  await screen.findByRole("button", { name: "Department" });
  expect(screen.getByRole("region", { name: "sidebar.department" })).toHaveTextContent("Department");
  expect(screen.getByRole("region", { name: "sidebar.personal" })).toHaveTextContent("Personal");
  expect(screen.queryByRole("region", { name: "sidebar.created" })).toBeNull();
  expect(screen.queryByRole("button", { name: "f118.create_space" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "sidebar.more_spaces" }));
  await screen.findByRole("button", { name: "Later personal" });
  expect(mocks.get.mock.calls.every(([url]) => String(url).endsWith("/admin/list"))).toBe(true);
  expect(mocks.get).toHaveBeenLastCalledWith("/api/v1/knowledge/space/admin/list", { params: { page: 2, page_size: 200 } });
});

it.each(["ordinary", "admin"] as const)("searches %s in its own scope and restores groups after clearing", async (view) => {
  const base = mocks.get.getMockImplementation()!;
  mocks.get.mockImplementation(async (url: string, options: { params: { keyword?: string } }) => {
    if (url.endsWith("/list")) {
      const rows = options.params.keyword ? [{ id: 10, name: "Search result", user_id: 99, space_kind: "normal" }] : [{ id: 7, name: "My space", space_kind: "normal" }];
      return view === "admin" ? { data: rows, total: rows.length } : { data: rows, has_more: false };
    }
    return base(url, options);
  });
  const f = setup({ scope: { ...scope, view } });
  render(f.draw());
  await screen.findByRole("button", { name: "My space" });
  const search = screen.getByRole("searchbox", { name: "sidebar.search" });
  fireEvent.change(search, { target: { value: "Search" } });
  await screen.findByRole("button", { name: "Search result" });
  expect(screen.queryByRole("button", { name: "My space" })).toBeNull();
  expect(mocks.get).toHaveBeenCalledWith(`/api/v1/knowledge/space/${view === "admin" ? "admin/" : ""}list`, { params: { page_size: 200, keyword: "Search", ...(view === "admin" ? { page: 1 } : {}) } });
  fireEvent.change(search, { target: { value: "" } });
  await screen.findByRole("button", { name: "My space" });
  expect(screen.queryByRole("button", { name: "Search result" })).toBeNull();
  expect(f.props.onSelect).not.toHaveBeenCalled();
});

it("ignores retired search results and advances sparse ordinary visible cursors", async () => {
  let finish!: (value: object) => void;
  const slow = new Promise((resolve) => { finish = resolve; });
  const base = mocks.get.getMockImplementation()!;
  mocks.get.mockImplementation((url: string, options: { params: { keyword?: string; cursor?: string } }) => {
    if (!url.endsWith("/list")) return base(url, options);
    if (options.params.keyword === "Old") return slow;
    return Promise.resolve(options.params.cursor ? { data: [{ id: 12, name: "Later visible", user_id: 99 }], has_more: false } : { data: [], has_more: true, next_cursor: "opaque/+==" });
  });
  const f = setup(); render(f.draw());
  const search = screen.getByRole("searchbox", { name: "sidebar.search" });
  fireEvent.change(search, { target: { value: "Old" } });
  await waitFor(() => expect(mocks.get).toHaveBeenCalledWith("/api/v1/knowledge/space/list", { params: { page_size: 200, keyword: "Old" } }));
  fireEvent.change(search, { target: { value: "New" } });
  fireEvent.click(await screen.findByRole("button", { name: "sidebar.more_spaces" }));
  await screen.findByRole("button", { name: "Later visible" });
  await act(async () => finish({ data: [{ id: 13, name: "Retired result" }], has_more: false }));
  expect(screen.queryByText("Retired result")).toBeNull();
  expect(mocks.get).toHaveBeenLastCalledWith("/api/v1/knowledge/space/list", { params: { page_size: 200, keyword: "New", cursor: "opaque/+==" } });
});
