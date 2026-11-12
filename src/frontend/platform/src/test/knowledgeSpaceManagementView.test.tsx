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
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpaceManagementView } from "@/pages/KnowledgePage/components/SpaceManagementView";
import { SpaceDirectoryToolbar } from "@/pages/KnowledgePage/components/SpaceDirectoryToolbar";

const mock = vi.hoisted(() => ({
  permission: vi.fn(),
  info: vi.fn(),
  folder: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({
  default: {},
  showApiError: vi.fn(),
}));
vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: mock.permission,
}));
vi.mock("@/controllers/API/knowledgeSpace", () => ({
  knowledgeSpaceApi: { getSpaceInfo: mock.info },
}));
vi.mock("@/pages/KnowledgePage/components/KnowledgeLibraryDialog", () => ({
  KnowledgeSpaceSettingsPanel: () => <p>settings-form</p>,
}));
vi.mock("@/pages/KnowledgePage/components/ProcessingDefaultsDialog", () => ({
  ProcessingDefaultsPanel: () => <p>defaults-form</p>,
}));
vi.mock("@/pages/KnowledgePage/components/SpaceProcessingDialog", () => ({
  SpaceProcessingPanel: ({ mode }: { mode: string }) => <p>{mode}-form</p>,
}));
vi.mock("@/components/bs-comp/permission/PermissionDialog", () => ({
  PermissionDialog: ({ resourceId }: { resourceId: string }) => (
    <div role="dialog">members-{resourceId}</div>
  ),
}));
const scope = {
  identityKey: "user:5",
  tenantId: 60,
  managementTenantId: 60,
  view: "ordinary" as const,
};
const clients: QueryClient[] = [];
function Location() {
  const loc = useLocation();
  return (
    <output data-testid="location">
      {loc.pathname}
      {loc.search}
    </output>
  );
}
function setup(path = "/filelib/7?parent_id=9&fileStatus=abnormal&keep=1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
  });
  clients.push(client);
  const draw = (currentScope = scope, spaceId = 7) => (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Location />
        <SpaceManagementView
          key={JSON.stringify([currentScope, spaceId])}
          scope={currentScope}
          spaceId={spaceId}
          title="Space"
          description="Description"
          parentId={9}
        >
          {(toolbarTarget) => (
            <>
              <p>directory-files</p>
              <SpaceDirectoryToolbar
                toolbarTarget={toolbarTarget}
                spaceId={spaceId}
                parentId={9}
                keyword=""
                onKeywordChange={vi.fn()}
                canCreateFolder
                canUpload
                onCreateFolder={mock.folder}
              />
            </>
          )}
        </SpaceManagementView>
      </MemoryRouter>
    </QueryClientProvider>
  );
  return { draw };
}
const tab = (name: string) =>
  fireEvent.mouseDown(screen.getByRole("tab", { name }), {
    button: 0,
    ctrlKey: false,
  });
beforeEach(() => {
  vi.resetAllMocks();
  mock.permission.mockResolvedValue({ actions: ["edit", "manage_permission"] });
  mock.info.mockResolvedValue({
    id: 7,
    name: "Root space",
    description: "Root description",
  });
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});

it("offers six authorized panels and preserves directory parameters when returning to files", async () => {
  const f = setup();
  render(f.draw());
  const tabs = await screen.findByRole("tablist");
  expect(within(tabs).getAllByRole("tab")).toHaveLength(6);
  expect(
    await screen.findByRole("heading", { name: "Root space" }),
  ).toBeVisible();
  expect(screen.queryByText("defaults-form")).toBeNull();
  tab("detail.defaults");
  expect(await screen.findByText("defaults-form")).toBeVisible();
  expect(screen.getByTestId("location")).toHaveTextContent(
    "parent_id=9&fileStatus=abnormal&keep=1&tab=defaults",
  );
  tab("detail.metadata");
  expect(await screen.findByText("schema-form")).toBeVisible();
  tab("detail.embedding");
  expect(await screen.findByText("embedding-form")).toBeVisible();
  tab("detail.jobs");
  expect(await screen.findByText("jobs-form")).toBeVisible();
  tab("detail.settings");
  expect(await screen.findByText("settings-form")).toBeVisible();
  tab("detail.files");
  expect(await screen.findByText("directory-files")).toBeVisible();
  expect(screen.getByTestId("location")).not.toHaveTextContent("tab=");
});

it("places file actions beside permissions and preserves upload directory parameters", async () => {
  const f = setup();
  render(f.draw());
  const header = (
    await screen.findByRole("button", { name: "detail.members" })
  ).closest("header")!;
  expect(
    within(header).getByRole("button", { name: "detail.batch" }),
  ).toBeVisible();
  fireEvent.keyDown(
    within(header).getByRole("button", { name: "detail.add" }),
    { key: "ArrowDown" },
  );
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "f118.create_folder" }),
  );
  expect(mock.folder).toHaveBeenCalledOnce();
  fireEvent.keyDown(
    within(header).getByRole("button", { name: "detail.add" }),
    { key: "ArrowDown" },
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: "uploadFile" }));
  expect(screen.getByTestId("location")).toHaveTextContent(
    "/filelib/upload/7?parent_id=9&fileStatus=abnormal&keep=1",
  );
  fireEvent.click(
    within(header).getByRole("button", { name: "detail.members" }),
  );
  expect(await screen.findByRole("dialog")).toHaveTextContent("members-7");
});

it.each(["denied", "failed"])(
  "keeps child-only files available when root configuration permission is %s",
  async (kind) => {
    if (kind === "failed")
      mock.permission.mockRejectedValue(new Error("unavailable"));
    else mock.permission.mockResolvedValue({ actions: [] });
    const f = setup("/filelib/7?parent_id=9&tab=settings");
    render(f.draw());
    expect(screen.getByText("directory-files")).toBeVisible();
    await waitFor(() =>
      expect(mock.permission).toHaveBeenCalledWith("knowledge_space", "7"),
    );
    expect(screen.queryByRole("tab", { name: "detail.settings" })).toBeNull();
    expect(screen.queryByRole("button", { name: "detail.members" })).toBeNull();
    expect(mock.info).not.toHaveBeenCalled();
  },
);

it("retires the old tenant's permissions and open member dialog", async () => {
  const f = setup();
  const view = render(f.draw());
  fireEvent.click(
    await screen.findByRole("button", { name: "detail.members" }),
  );
  expect(screen.getByRole("dialog")).toBeVisible();
  let resolve!: (value: { actions: string[] }) => void;
  mock.permission.mockReturnValueOnce(
    new Promise((done) => {
      resolve = done;
    }),
  );
  view.rerender(f.draw({ ...scope, tenantId: 61, managementTenantId: 61 }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.queryByRole("tab", { name: "detail.settings" })).toBeNull();
  await act(async () => resolve({ actions: [] }));
  expect(screen.getByText("directory-files")).toBeVisible();
});
