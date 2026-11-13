import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { KnowledgeSpaceSidebar } from "./KnowledgeSpaceSidebar";

const mocks = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), children: vi.fn(), parents: vi.fn(), error: vi.fn(),
}));
vi.mock("./useSidebarSpaceActions", () => ({ useSidebarSpaceActions: () => ({ load: vi.fn(), render: () => null, dialogs: null }) }));
vi.mock("@/controllers/request", () => ({ default: { get: mocks.get, post: mocks.post }, showApiError: mocks.error }));
vi.mock("@/controllers/API/knowledgeSpace", () => ({ knowledgeSpaceApi: { listChildren: mocks.children } }));
vi.mock("@/controllers/API/knowledgeFiles", () => ({ knowledgeFilesApi: { listSpaceFolderParents: mocks.parents } }));
vi.mock("@/controllers/hooks/knowledge", () => ({
  knowledgeQueryKeys: {
    scope: (scope: { identityKey: string; tenantId: number; managementTenantId: number | null; view: string }) => ["f118-knowledge", scope.identityKey, scope.tenantId, scope.managementTenantId, scope.view],
    space: (scope: { identityKey: string; tenantId: number; managementTenantId: number | null; view: string }, id: number) => ["f118-knowledge", scope.identityKey, scope.tenantId, scope.managementTenantId, scope.view, "space", id],
  },
}));
vi.mock("@bisheng/ui", () => ({
  Tooltip: ({ children }: { children: ReactNode }) => children,
  Button: ({ children, onClick, disabled, "aria-label": label }: ButtonHTMLAttributes<HTMLButtonElement>) => <button type="button" onClick={onClick} disabled={disabled} aria-label={label}>{children}</button>,
  Dropdown: ({ children, menu }: { children: ReactNode; menu: ReactNode }) => {
    const [open, setOpen] = useState(false);
    return <div><div onClick={() => setOpen((value) => !value)}>{children}</div>{open && <div role="menu">{menu}</div>}</div>;
  },
  DropdownItem: ({ children, onSelect, disabled }: { children: ReactNode; onSelect: () => void; disabled?: boolean }) => <button type="button" role="menuitem" disabled={disabled} onClick={onSelect}>{children}</button>,
}));

const scope = { identityKey: "user:2", tenantId: 60, managementTenantId: 60, view: "ordinary" as const };
const page = (data: { id: number; knowledge_id: number; file_name: string; file_type: number }[], hasMore = false, cursor: string | null = null) => ({ data, page_size: 100, has_more: hasMore, next_cursor: cursor });
const folder = (id: number, name: string) => ({ id, knowledge_id: 7, file_name: name, file_type: 0 });
const clients: QueryClient[] = [];
function setup(extra = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const props = { scope, canCreate: true, onCreate: vi.fn(), onSelect: vi.fn(), ...extra };
  const draw = (next = props) => <QueryClientProvider client={client}><KnowledgeSpaceSidebar {...next} /></QueryClientProvider>;
  return { props, draw, client };
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.get.mockImplementation((url: string) => Promise.resolve(url.endsWith("/mine") ? [{ id: 7, name: "My space", is_pinned: false }] : []));
  mocks.post.mockResolvedValue(true);
  mocks.children.mockResolvedValue(page([]));
  mocks.parents.mockResolvedValue([]);
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

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
  fireEvent.click(screen.getByRole("button", { name: "f118.create_space" }));
  expect(f.props.onCreate).toHaveBeenCalledTimes(1);
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

it("collapses the sidebar without losing expanded folders or fetching them again", async () => {
  mocks.children.mockResolvedValue(page([folder(9, "Root folder")]));
  const f = setup();
  render(f.draw());
  fireEvent.click(await screen.findByRole("button", { name: "sidebar.expand My space" }));
  await screen.findByRole("button", { name: "Root folder" });
  expect(screen.queryByRole("heading", { name: "f118.spaces" })).toBeNull();
  const reads = mocks.children.mock.calls.length;
  fireEvent.click(screen.getByRole("button", { name: "sidebar.collapse_navigation" }));
  expect(screen.queryByRole("button", { name: "Root folder" })).toBeNull();
  expect(screen.getByRole("complementary")).toHaveClass("w-10");
  fireEvent.click(screen.getByRole("button", { name: "sidebar.expand_navigation" }));
  expect(screen.getByRole("button", { name: "Root folder" })).toBeVisible();
  expect(mocks.children).toHaveBeenCalledTimes(reads);
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
  expect(mocks.parents).toHaveBeenCalledWith(7, 12);
});

it("sorts only the selected group and pins through the existing API contract", async () => {
  const f = setup();
  render(f.draw());
  await screen.findByRole("button", { name: "My space" });
  fireEvent.click(screen.getByRole("button", { name: "sidebar.sort sidebar.created" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "sidebar.sort_name" }));
  await waitFor(() => expect(mocks.get).toHaveBeenCalledWith("/api/v1/knowledge/space/mine", { params: { order_by: "name" } }));
  expect(mocks.get).not.toHaveBeenCalledWith("/api/v1/knowledge/space/joined", { params: { order_by: "name" } });
  fireEvent.click(screen.getByRole("button", { name: "more My space" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "sidebar.pin" }));
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
  view.rerender(f.draw({ ...f.props, canCreate: false, scope: { ...scope, tenantId: 202, managementTenantId: 202 } }));
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
