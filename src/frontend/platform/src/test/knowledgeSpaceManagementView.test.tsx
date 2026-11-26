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
import { MemoryRouter, useLocation, useNavigationType } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpaceManagementView } from "@/pages/KnowledgePage/components/SpaceManagementView";
import { SpaceDirectoryToolbar } from "@/pages/KnowledgePage/components/SpaceDirectoryToolbar";
import type {
  DeletePrecheck,
  DeletionStatus,
} from "@/controllers/API/knowledgeDeletion";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";

const mock = vi.hoisted(() => ({
  permission: vi.fn(),
  info: vi.fn(),
  folder: vi.fn(),
  readMetadataSchema: vi.fn(),
  listProcessingJobs: vi.fn(),
  precheckDeletion: vi.fn(),
  confirmDeletion: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({
  default: {},
  showApiError: vi.fn(),
}));
vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: mock.permission,
}));
vi.mock("@/controllers/API/knowledgeSpace", () => ({
  knowledgeSpaceApi: {
    getSpaceInfo: mock.info,
    listProcessingJobs: mock.listProcessingJobs,
  },
}));
vi.mock("@/controllers/API/knowledgeProcessing", () => ({
  readMetadataSchema: mock.readMetadataSchema,
}));
vi.mock("@/controllers/API", () => ({
  addMetadata: vi.fn(),
  deleteMetadataFields: vi.fn(),
  updateMetadataFields: vi.fn(),
}));
vi.mock("@/controllers/API/knowledgeDeletion", () => ({
  precheckDeletion: mock.precheckDeletion,
  confirmDeletion: mock.confirmDeletion,
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
  const navigationType = useNavigationType();
  return (
    <output data-testid="location" data-navigation-type={navigationType}>
      {loc.pathname}
      {loc.search}
    </output>
  );
}
function setup(path = "/filelib/7?parent_id=9&fileStatus=abnormal&keep=1", hasFiles = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
  });
  clients.push(client);
  const draw = (currentScope: KnowledgeQueryScope = scope, spaceId = 7) => (
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
          {hasFiles ? (toolbarTarget) => (
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
          ) : undefined}
        </SpaceManagementView>
      </MemoryRouter>
    </QueryClientProvider>
  );
  return { draw };
}
async function openMore() {
  fireEvent.keyDown(await screen.findByRole("button", { name: "more" }), {
    key: "ArrowDown",
  });
  return screen.findByRole("menu");
}

async function selectMoreItem(name: string) {
  fireEvent.click(within(await openMore()).getByRole("menuitem", { name }));
}
beforeEach(() => {
  vi.resetAllMocks();
  mock.permission.mockResolvedValue({ actions: ["edit", "manage_permission"] });
  mock.info.mockResolvedValue({
    id: 7,
    name: "Root space",
    description: "Root description",
  });
  mock.readMetadataSchema.mockResolvedValue({ revision: 5, fields: [] });
  mock.listProcessingJobs.mockResolvedValue({ data: [], total: 0 });
  mock.precheckDeletion.mockResolvedValue({
    confirmation_id: "plan-7",
    plan_digest: "digest",
    expires_at: "2030-01-01T00:00:00Z",
    check_complete: true,
    can_execute: true,
    requires_skip_confirmation: false,
    valid_items: [{ id: 7, type: "space", name: "Space" }],
    invalid_items: [],
    impact: {
      file_count: 0,
      source_counts: {},
      restricted_counts: {},
      source_page: { data: [], page_size: 50, has_more: false, next_cursor: null },
    },
  } satisfies DeletePrecheck);
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});

it.each(["ordinary", "admin"] as const)(
  "opens metadata over the directory and routes settings separately in the %s view",
  async (view) => {
    const directory = `/filelib/7?parent_id=9&fileStatus=abnormal&keep=1${view === "admin" ? "&view=admin" : ""}`;
    const f = setup(directory);
    render(f.draw({ ...scope, view }));
    expect(await screen.findByRole("heading", { name: "Root space" })).toBeVisible();
    const files = screen.getByText("directory-files");
    expect(files).toBeVisible();
    expect(screen.queryByRole("tablist")).toBeNull();

    await selectMoreItem("detail.metadata");
    const metadata = await screen.findByRole("dialog", { name: "metaData" });
    expect(await within(metadata).findByText("document_id")).toBeVisible();
    expect(mock.readMetadataSchema).toHaveBeenCalledWith(7);
    expect(files).toBeInTheDocument();
    expect(screen.getByTestId("location").textContent).toBe(directory);
    fireEvent.keyDown(metadata, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "metaData" })).toBeNull();
    expect(screen.getByText("directory-files")).toBe(files);
    expect(screen.getByTestId("location").textContent).toBe(directory);

    await selectMoreItem("detail.settings");
    const location = screen.getByTestId("location");
    expect(location.textContent).toBe(directory.replace("/filelib/7?", "/filelib/7/settings?"));
    expect(location).toHaveAttribute("data-navigation-type", "PUSH");
  },
);

it("opens a legacy metadata link over the directory and clears only its tab on close", async () => {
  const directory = "/filelib/7?parent_id=9&fileStatus=abnormal&keep=1";
  const f = setup(`${directory}&tab=metadata`);
  render(f.draw());
  const metadata = await screen.findByRole("dialog", { name: "metaData" });
  const files = screen.getByText("directory-files");
  expect(files).toBeInTheDocument();

  fireEvent.keyDown(metadata, { key: "Escape" });

  expect(screen.queryByRole("dialog", { name: "metaData" })).toBeNull();
  expect(screen.getByText("directory-files")).toBe(files);
  const location = screen.getByTestId("location");
  expect(location.textContent).toBe(directory);
  expect(location).toHaveAttribute("data-navigation-type", "REPLACE");
});

it("keeps the file actions in the header and opens permissions from More", async () => {
  const f = setup();
  render(f.draw());
  const header = (
    await screen.findByRole("button", { name: "more" })
  ).closest("header")!;
  expect(within(header).queryByRole("button", { name: "detail.members" })).toBeNull();
  expect(
    within(header).queryByRole("button", { name: "detail.batch" }),
  ).toBeNull();
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
  await selectMoreItem("managePermission");
  expect(await screen.findByRole("dialog")).toHaveTextContent("members-7");
});

it.each([
  { action: "edit", visible: ["detail.metadata", "detail.settings"] },
  { action: "manage_permission", visible: ["managePermission"] },
])("limits More menus to the $action permission", async ({ action, visible }) => {
  mock.permission.mockResolvedValue({ actions: [action] });
  const f = setup();
  render(f.draw());
  const menu = within(await openMore());
  expect(menu.getAllByRole("menuitem")).toHaveLength(visible.length);
  visible.forEach((name) => expect(menu.getByRole("menuitem", { name })).toBeVisible());
});

it.each([
  { view: "ordinary", list: "/filelib", search: "" },
  { view: "admin", list: "/filelib?view=admin", search: "&view=admin" },
] as const)(
  "requires confirmation before deleting and replaces the detail page in the $view view",
  async ({ view, list, search }) => {
    mock.permission.mockResolvedValue({ actions: ["delete"] });
    let complete!: (result: DeletionStatus) => void;
    mock.confirmDeletion.mockReturnValue(
      new Promise<DeletionStatus>((resolve) => {
        complete = resolve;
      }),
    );
    const directory = `/filelib/7?parent_id=9${search}`;
    const f = setup(directory);
    render(f.draw({ ...scope, view }));
    const menu = within(await openMore());
    expect(menu.getAllByRole("menuitem")).toHaveLength(1);
    expect(mock.precheckDeletion).not.toHaveBeenCalled();
    fireEvent.click(
      menu.getByRole("menuitem", { name: "deletion.delete_space" }),
    );

    const dialog = await screen.findByRole("dialog", {
      name: "deletion.delete_space",
    });
    const confirm = within(dialog).getByRole("button", {
      name: "deletion.confirm",
    });
    await waitFor(() => expect(confirm).toBeEnabled());
    expect(mock.precheckDeletion).toHaveBeenCalledExactlyOnceWith(
      { spaceId: 7, kind: "delete" },
      false,
    );
    expect(mock.confirmDeletion).not.toHaveBeenCalled();

    fireEvent.click(confirm);
    expect(mock.confirmDeletion).toHaveBeenCalledExactlyOnceWith(7, {
      confirmation_id: "plan-7",
      plan_digest: "digest",
      idempotency_key: "delete:plan-7",
    });
    expect(screen.getByTestId("location").textContent).toBe(directory);
    await act(async () => complete({ job_id: "plan-7", state: "succeeded" }));
    const location = screen.getByTestId("location");
    expect(location.textContent).toBe(list);
    expect(location).toHaveAttribute("data-navigation-type", "REPLACE");
    expect(
      screen.queryByRole("dialog", { name: "deletion.delete_space" }),
    ).toBeNull();
  },
);

it("keeps the directory open when space deletion is cancelled", async () => {
  mock.permission.mockResolvedValue({ actions: ["delete"] });
  const directory = "/filelib/7?parent_id=9";
  const f = setup(directory);
  render(f.draw());
  const menu = within(await openMore());
  await act(async () => {
    fireEvent.click(menu.getByRole("menuitem", { name: "deletion.delete_space" }));
  });
  const dialog = await screen.findByRole("dialog", {
    name: "deletion.delete_space",
  });
  const close = within(dialog).getByRole("button", { name: "deletion.close" });
  await waitFor(() => expect(close).toBeEnabled());
  fireEvent.click(close);
  await act(async () => {
    await new Promise<number>((resolve) => requestAnimationFrame(resolve));
  });
  expect(
    screen.queryByRole("dialog", { name: "deletion.delete_space" }),
  ).toBeNull();
  expect(screen.getByRole("button", { name: "more" })).toHaveFocus();
  expect(screen.getByTestId("location").textContent).toBe(directory);
  expect(mock.confirmDeletion).not.toHaveBeenCalled();
});

it("returns to the management list after closing a direct management metadata link", async () => {
  const f = setup("/filelib/7?view=admin&tab=metadata", false);
  render(f.draw({ ...scope, view: "admin" }));
  const metadata = await screen.findByRole("dialog", { name: "metaData" });
  fireEvent.keyDown(metadata, { key: "Escape" });
  expect(screen.queryByRole("dialog", { name: "metaData" })).toBeNull();
  expect(screen.getByTestId("location").textContent).toBe("/filelib?view=admin");
});

it.each(["denied", "failed"])(
  "keeps child-only files available when root configuration permission is %s",
  async (kind) => {
    if (kind === "failed")
      mock.permission.mockRejectedValue(new Error("unavailable"));
    else mock.permission.mockResolvedValue({ actions: [] });
    const directory = `/filelib/7?parent_id=9&tab=${kind === "denied" ? "embedding" : "settings"}`;
    const f = setup(directory);
    render(f.draw());
    expect(screen.getByText("directory-files")).toBeVisible();
    await waitFor(() =>
      expect(mock.permission).toHaveBeenCalledWith("knowledge_space", "7", { showError: false }),
    );
    expect(screen.queryByRole("button", { name: "more" })).toBeNull();
    expect(screen.getByTestId("location").textContent).toBe(directory);
    expect(mock.info).not.toHaveBeenCalled();
  },
);

it("retires the old tenant's permissions and open member dialog", async () => {
  const f = setup();
  const view = render(f.draw());
  await selectMoreItem("managePermission");
  expect(screen.getByRole("dialog")).toBeVisible();
  let resolve!: (value: { actions: string[] }) => void;
  mock.permission.mockReturnValueOnce(
    new Promise((done) => {
      resolve = done;
    }),
  );
  view.rerender(f.draw({ ...scope, tenantId: 61, managementTenantId: 61 }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.queryByRole("button", { name: "more" })).toBeNull();
  await act(async () => resolve({ actions: [] }));
  expect(screen.getByText("directory-files")).toBeVisible();
});

it.each(["settings", "defaults", "embedding", "jobs"])(
  "replaces the legacy %s link with standalone settings while preserving the directory",
  async (legacyTab) => {
    const directory = "/filelib/7?parent_id=9&fileStatus=abnormal&keep=1&view=admin";
    const f = setup(`${directory}&tab=${legacyTab}`);
    render(f.draw({ ...scope, view: "admin" }));
    const location = screen.getByTestId("location");
    await waitFor(() => expect(location.textContent).toBe(directory.replace("/filelib/7?", "/filelib/7/settings?")));
    expect(location).toHaveAttribute("data-navigation-type", "REPLACE");
  },
);
