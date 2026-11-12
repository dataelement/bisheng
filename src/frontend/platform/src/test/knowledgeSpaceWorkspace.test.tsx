import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import KnowledgePage from "@/pages/KnowledgePage";
import { userContext } from "@/contexts/userContext";
import type { FilesProps } from "@/pages/KnowledgePage/components/Files";

const mock = vi.hoisted(() => ({ get: vi.fn(), scope: vi.fn() }));
vi.mock("@/contexts/userContext", async () => ({ userContext: (await import("react")).createContext({ user: {} }) }));
vi.mock("@/hooks/useKnowledgePageScope", () => ({ useKnowledgePageScope: mock.scope }));
vi.mock("@/controllers/API/permission", () => ({ getMyResourcePermissionsApi: async () => ({ actions: [] }) }));
vi.mock("@/controllers/request", () => ({ default: { get: mock.get }, showApiError: vi.fn() }));
vi.mock("@/pages/KnowledgePage/KnowledgeFile", () => ({ default: ({ scope }: { scope: { view: string } }) => <p>{scope.view}-list</p> }));
vi.mock("@/pages/KnowledgePage/KnowledgeQa", () => ({ default: () => <p>qa-list</p> }));
vi.mock("@/pages/KnowledgePage/components/KnowledgeLibraryDialog", () => ({ KnowledgeLibraryDialog: () => null }));
vi.mock("@/pages/KnowledgePage/components/Files", () => ({ default: (props: FilesProps) => <output data-testid="files">{JSON.stringify({ id: props.spaceId, parent: props.parentId, presentation: props.presentation })}</output> }));

const scope = { identityKey: "user:5", tenantId: 60, managementTenantId: 60, view: "ordinary" } as const;
const clients: QueryClient[] = [];
function Location() { const location = useLocation(); return <output data-testid="location">{location.pathname}{location.search}</output>; }
function mount(path = "/filelib") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  return render(<QueryClientProvider client={client}><userContext.Provider value={{ user: { user_id: 5 }, setUser: vi.fn(), savedComponents: [], addSavedComponent: async () => undefined, checkComponentsName: () => false, delComponent: vi.fn() }}><MemoryRouter initialEntries={[path]}><Location /><Routes><Route path="/filelib" element={<KnowledgePage />} /><Route path="/filelib/:id" element={<KnowledgePage />} /></Routes></MemoryRouter></userContext.Provider></QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  mock.scope.mockReturnValue({ scopes: { ordinary: scope, admin: { ...scope, view: "admin" } }, canManage: true, isLoading: false, retry: vi.fn() });
  mock.get.mockImplementation(async (url: string, options?: { params?: { file_type?: number; parent_id?: number | null } }) => {
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
  fireEvent.click(await within(tree).findByRole("button", { name: "sidebar.expand Reports" }));
  fireEvent.click(await within(tree).findByRole("button", { name: "Finance" }));
  await waitFor(() => expect(screen.getByTestId("files")).toHaveTextContent('"parent":9'));
  expect(screen.getByTestId("location")).toHaveTextContent("/filelib/7?fileStatus=abnormal&keep=1&parent_id=9");
  expect(screen.getByTestId("files")).toHaveTextContent('"presentation":"workspace"');
  expect(within(screen.getByRole("complementary")).getByRole("button", { name: "Finance" })).toHaveAttribute("aria-current", "page");
  fireEvent.click(within(screen.getByRole("complementary")).getByRole("button", { name: "sidebar.all_spaces" }));
  expect(await screen.findByText("ordinary-list")).toBeVisible();
});

it("opens deep folder links while preserving the independent QA and management tabs", async () => {
  mount("/filelib/7?parent_id=9");
  expect(await screen.findByTestId("files")).toHaveTextContent('"parent":9');
  const tree = screen.getByRole("complementary");
  expect(await within(tree).findByRole("button", { name: "Finance" })).toHaveAttribute("aria-current", "page");
  fireEvent.mouseDown(screen.getByRole("tab", { name: "lib.qaData" }), { button: 0, ctrlKey: false });
  expect(await screen.findByText("qa-list")).toBeVisible();
  fireEvent.mouseDown(screen.getByRole("tab", { name: "f118.manage_spaces" }), { button: 0, ctrlKey: false });
  expect(await screen.findByText("admin-list")).toBeVisible();
  expect(screen.queryByRole("complementary")).toBeNull();
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
