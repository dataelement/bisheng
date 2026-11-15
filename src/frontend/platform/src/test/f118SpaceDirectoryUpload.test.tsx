import { uploadSettings } from "./uploadWizardFixtures";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Files from "@/pages/KnowledgePage/components/Files";
import FilesUpload from "@/pages/KnowledgePage/filesUpload";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  permissions: vi.fn(),
  action: vi.fn(),
  error: vi.fn(),
  legacy: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({
  default: { get: mocks.get, post: mocks.post, put: mocks.put },
  showApiError: mocks.error,
}));
vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: mocks.permissions,
  checkResourceActionApi: mocks.action,
}));
vi.mock("@/controllers/API", () => ({
  readFileByLibDatabase: mocks.legacy,
  getKnowledgeDetailApi: mocks.legacy,
}));
// Defaults render only controlled fields, not the legacy drag-and-drop editor.
vi.mock("@/pages/KnowledgePage/components/FileUploadSplitStrategy", () => ({ default: () => null }));
vi.mock("@/pages/KnowledgePage/components/PreviewFile", () => ({
  default: () => null,
}));
vi.mock("@/contexts/locationContext", async () => ({
  locationContext: (await import("react")).createContext({
    appConfig: {
      enableEtl4lm: true,
      enableMediaUpload: false,
      uploadFileMaxSize: 50,
    },
  }),
}));
vi.mock("@/hooks/useKnowledgePageScope", () => ({
  useKnowledgePageScope: () => ({
    scopes: { ordinary: { ...currentScope, view: "ordinary" }, admin: { ...currentScope, view: "admin" } },
    canManage: true,
    isLoading: false,
    retry: vi.fn(),
  }),
}));
const base: KnowledgeQueryScope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary",
};
let currentScope: KnowledgeQueryScope;
let grants: Map<string, string[]>;
const clients: QueryClient[] = [];
const permission = (actions: string[] = []) => ({
  actions,
  mode: "INHERIT",
  sources: [],
  roster_complete: true,
});
const row = (id = 11, status = 2) => ({
  id,
  knowledge_id: 7,
  file_name: "report.md",
  file_type: 1,
  status,
});
const page = (data = [row()]) => ({
  data,
  page_size: 40,
  has_more: false,
  next_cursor: null,
});
function mount(parentId: number | null = null) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  function Location() {
    const location = useLocation();
    return (
      <output data-testid="location">
        {location.pathname}
        {location.search}
      </output>
    );
  }
  const initial = `/filelib/7?keep=1&fileStatus=abnormal${parentId === null ? "" : `&parent_id=${parentId}`}${currentScope.view === "admin" ? "&view=admin" : ""}`;
  const view = (parent: number | null) => (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initial]}>
        <Location />
        <Routes>
          <Route
            path="/filelib/:id"
            element={
              <Files scope={currentScope} spaceId={7} parentId={parent} />
            }
          />
          <Route path="/filelib/upload/:id" element={<FilesUpload />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
  const result = render(view(parentId));
  return {
    ...result,
    client,
    update: (parent = parentId) => result.rerender(view(parent)),
  };
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.action.mockResolvedValue({ allowed: false });
  currentScope = base;
  grants = new Map();
  mocks.permissions.mockImplementation(async (type: string, id: string) =>
    permission(grants.get(`${type}:${id}`)),
  );
  mocks.get.mockImplementation(
    async (url: string, options?: { params?: { file_ids?: number[] } }) => {
      if (url.endsWith("/upload-settings")) return uploadSettings();
      if (url.endsWith("/children"))
        return page(options?.params?.file_ids?.map((id) => row(id)));
      throw new Error(`unexpected read ${url}`);
    },
  );
  mocks.post.mockImplementation(async (url: string) => {
    if (url === "/api/v1/knowledge/space/7/uploads")
      return { file_path: "tmp/report.md", upload_id: "a".repeat(32), repeat: false };
    if (url === "/api/v1/knowledge/space/7/files") return [row(81, 5)];
    throw new Error(`unexpected write ${url}`);
  });
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});

it.each([null, 9])(
  "exposes upload from only the actual container upload_file action: parent %s",
  async (parentId) => {
    const type = parentId === null ? "knowledge_space" : "folder";
    grants.set(`${type}:${parentId ?? 7}`, ["upload_file"]);
    mount(parentId);
    expect(
      await screen.findByRole("button", { name: "uploadFile" }),
    ).toBeInTheDocument();
    expect(mocks.permissions).toHaveBeenCalledExactlyOnceWith(
      type,
      String(parentId ?? 7),
    );
    expect(
      screen.queryByRole("button", { name: "f118.create_folder" }),
    ).not.toBeInTheDocument();
  },
);
it.each([
  { actions: ["visible"] },
  { actions: ["edit"] },
  { actions: ["create_folder"] },
  { actions: [] },
])(
  "does not borrow other container actions as upload_file: %j",
  async ({ actions }) => {
    grants.set("knowledge_space:7", actions);
    mount();
    await screen.findByText("report.md");
    expect(
      screen.queryByRole("button", { name: "uploadFile" }),
    ).not.toBeInTheDocument();
  },
);
it("preserves management scope and folder context through upload and return", async () => {
  currentScope = { ...base, view: "admin" };
  grants.set("folder:9", ["upload_file"]);
  const current = mount(9);
  fireEvent.click(await screen.findByRole("button", { name: "uploadFile" }));
  expect(screen.getByTestId("location")).toHaveTextContent("/filelib/upload/7?keep=1&fileStatus=abnormal&parent_id=9&view=admin");
  await waitFor(() => expect(document.querySelector('input[type="file"]')).not.toBeNull());
  const uploadQuery = current.client.getQueryCache().getAll().find((query) => query.queryKey.includes("upload-target"));
  expect(uploadQuery?.queryKey[4]).toBe("admin");
  fireEvent.click(screen.getByRole("button", { name: "backToKnowledge" }));
  expect(await screen.findByText("report.md")).toBeVisible();
  expect(screen.getByTestId("location")).toHaveTextContent("/filelib/7?keep=1&fileStatus=abnormal&parent_id=9&view=admin");
});
it("navigates the real folder entry into the real upload route, register and exact-ID status chain", async () => {
  grants.set("folder:9", ["upload_file"]);
  mount(9);
  fireEvent.click(await screen.findByRole("button", { name: "uploadFile" }));
  const location = new URL(
    `https://platform.test${screen.getByTestId("location").textContent}`,
  );
  expect(location.pathname).toBe("/filelib/upload/7");
  expect([...location.searchParams]).toEqual([
    ["keep", "1"],
    ["fileStatus", "abnormal"],
    ["parent_id", "9"],
  ]);
  await waitFor(() =>
    expect(document.querySelector('input[type="file"]')).not.toBeNull(),
  );
  await act(async () =>
    fireEvent.change(document.querySelector('input[type="file"]')!, {
      target: {
        files: [new File(["content"], "report.md", { type: "text/markdown" })],
      },
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "uploadDirectly" }));
  await screen.findByText("completed");
  expect(mocks.post.mock.calls.map(([url]) => url)).toEqual([
    "/api/v1/knowledge/space/7/uploads",
    "/api/v1/knowledge/space/7/files",
  ]);
  expect(mocks.post.mock.calls[1][1]).toMatchObject({
    file_path: ["tmp/report.md"],
    parent_id: 9,
  });
  expect(mocks.get).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/7/children",
    { params: { parent_id: 9, file_ids: [81], page_size: 100 } },
  );
  expect(mocks.permissions.mock.calls).toEqual([
    ["folder", "9"],
    ["folder", "9"],
  ]);
  expect(mocks.legacy).not.toHaveBeenCalled();
  expect(
    mocks.get.mock.calls.every(([url]) => (String(url).endsWith("/children") || String(url).endsWith("/upload-settings"))),
  ).toBe(true);
});
it("keeps root navigation at root while retaining unrelated directory query", async () => {
  grants.set("knowledge_space:7", ["upload_file", "create_folder"]);
  mount();
  expect(
    await screen.findByRole("button", { name: "f118.create_folder" }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "uploadFile" }));
  const location = new URL(
    `https://platform.test${screen.getByTestId("location").textContent}`,
  );
  expect(location.pathname).toBe("/filelib/upload/7");
  expect(location.searchParams.has("parent_id")).toBe(false);
  expect(location.searchParams.get("keep")).toBe("1");
  expect(location.searchParams.get("fileStatus")).toBe("abnormal");
});
it.each(["scope", "parent"])(
  "does not revive a late container grant through %s A-B-A",
  async (kind) => {
    let resolve!: (value: ReturnType<typeof permission>) => void;
    const pending = new Promise<ReturnType<typeof permission>>((yes) => {
      resolve = yes;
    });
    mocks.permissions
      .mockReturnValueOnce(pending)
      .mockResolvedValue(permission());
    const view = mount(9);
    await waitFor(() => expect(mocks.permissions).toHaveBeenCalledTimes(1));
    if (kind === "scope")
      currentScope = { ...base, tenantId: 202, managementTenantId: 202 };
    view.update(kind === "parent" ? 10 : 9);
    await waitFor(() => expect(mocks.permissions).toHaveBeenCalledTimes(2));
    currentScope = base;
    view.update(9);
    await waitFor(() => expect(mocks.permissions).toHaveBeenCalledTimes(3));
    await act(async () => resolve(permission(["upload_file"])));
    expect(
      screen.queryByRole("button", { name: "uploadFile" }),
    ).not.toBeInTheDocument();
  },
);
