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
import { MemoryRouter } from "react-router-dom";
import { useContext, type ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Files from "@/pages/KnowledgePage/components/Files";
import { locationContext } from "@/contexts/locationContext";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  permissions: vi.fn(),
  batch: vi.fn(),
  error: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({
  default: { get: mocks.get, post: mocks.post },
  showApiError: mocks.error,
}));
vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: mocks.permissions,
}));
vi.mock("@/controllers/API", () => ({ getKnowledgeDetailApi: vi.fn() }));
vi.mock("@/pages/KnowledgePage/hooks/useKnowledgeBatch", () => ({
  useKnowledgeBatch: () => ({ open: mocks.batch, view: null }),
}));
vi.mock("@/pages/KnowledgePage/components/PreviewFile", () => ({
  default: () => null,
}));
vi.mock("@/components/bs-comp/permission/PermissionDialog", () => ({
  PermissionDialog: (props: {
    resourceType: string;
    resourceId: string;
    resourceName: string;
  }) => (
    <div
      role="dialog"
      aria-label="permission-editor"
    >{`${props.resourceType}:${props.resourceId}:${props.resourceName}`}</div>
  ),
}));
vi.mock("@/pages/KnowledgePage/components/tags/KnowledgeTagSelect", () => ({
  default: (props: {
    open: boolean;
    fileIds: number[];
    initialTags: unknown;
  }) =>
    props.open && (
      <div role="dialog" aria-label="tag-editor">
        {JSON.stringify([props.fileIds, props.initialTags])}
      </div>
    ),
}));
vi.mock("@/pages/KnowledgePage/components/MoveDialog", () => ({
  MoveDialog: (props: { items: unknown }) => (
    <div role="dialog" aria-label="move-editor">
      {JSON.stringify(props.items)}
    </div>
  ),
}));
vi.mock("@/pages/KnowledgePage/components/SpaceVersionHistorySheet", () => ({
  SpaceVersionHistorySheet: (props: {
    open: boolean;
    fileId: number;
  }) =>
    props.open && (
      <div role="dialog" aria-label="version-history">
        {props.fileId}
      </div>
    ),
}));
vi.mock("@/pages/KnowledgePage/components/SpaceSimilarDocumentDialog", () => ({
  SpaceSimilarDocumentDialog: ({ fileId, file, restrictToFileIds, onOpenChange }: {
    fileId?: number;
    file?: { name: string };
    restrictToFileIds?: number[];
    onOpenChange: (open: boolean) => void;
  }) => (
    <div role="dialog" aria-label={fileId === undefined ? "similar-documents" : "version-management"}>
      {JSON.stringify(fileId === undefined ? restrictToFileIds : [fileId, file?.name])}
      <button type="button" onClick={() => onOpenChange(false)}>close</button>
    </div>
  ),
}));
const scope: KnowledgeQueryScope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "admin",
};
const file = (
  id = 11,
  extra: Partial<KnowledgeSpaceChild> = {},
): KnowledgeSpaceChild => ({
  id,
  knowledge_id: 7,
  file_name: `file-${id}.pdf`,
  file_type: 1,
  status: 2,
  ...extra,
});
const clients: QueryClient[] = [];
let rows: KnowledgeSpaceChild[];
let actions: string[];
let rootActions: string[];
function Environment({
  enabled,
  children,
}: {
  enabled: boolean;
  children: ReactNode;
}) {
  const defaults = useContext(locationContext);
  return (
    <locationContext.Provider
      value={{ ...defaults, appConfig: { versionManagementEnabled: enabled } }}
    >
      {children}
    </locationContext.Provider>
  );
}
function mount(
  presentation?: "workspace",
  enabled = false,
  toolbarTarget?: HTMLDivElement,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  const draw = (currentScope = scope) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Environment enabled={enabled}>
          <Files
            scope={currentScope}
            spaceId={7}
            presentation={presentation}
            toolbarTarget={toolbarTarget}
          />
        </Environment>
      </MemoryRouter>
    </QueryClientProvider>
  );
  const result = render(draw());
  return {
    ...result,
    update: (currentScope: KnowledgeQueryScope) =>
      result.rerender(draw(currentScope)),
  };
}
async function menu(name = "file-11.pdf") {
  fireEvent.keyDown(await screen.findByLabelText(`more ${name}`), {
    key: "Enter",
  });
  const opened = await screen.findByRole("menu");
  await waitFor(() =>
    expect(within(opened).queryByText("loading")).not.toBeInTheDocument(),
  );
  return opened;
}
beforeEach(() => {
  vi.clearAllMocks();
  rows = [file()];
  actions = ["visible", "rename", "move", "manage_permission"];
  rootActions = ["visible", "edit", "manage_permission"];
  mocks.get.mockImplementation(async () => ({
    data: rows,
    has_more: false,
    next_cursor: null,
    page_size: 40,
  }));
  mocks.post.mockResolvedValue({ valid_items: [] });
  mocks.permissions.mockImplementation(async (type: string) => ({
    actions: type === "knowledge_space" ? rootActions : actions,
  }));
  mocks.batch.mockResolvedValue(null);
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});

it.each([undefined, "workspace"] as const)(
  "shows only server-reported folder anomalies in presentation %s",
  async (presentation) => {
    rows = [
      file(9, {
        file_name: "Failed folder",
        file_type: 0,
        has_abnormal_files: true,
      }),
      file(10, { file_name: "Healthy folder", file_type: 0 }),
    ];
    mount(presentation);
    await screen.findByText("Failed folder");
    expect(screen.getAllByText("fileStatusAbnormal")).toHaveLength(1);
    if (presentation) {
      fireEvent.click(
        screen.getByRole("button", { name: "workspace.card_view" }),
      );
      expect(screen.getAllByText("fileStatusAbnormal")).toHaveLength(1);
    }
  },
);

it.each([0, 1])(
  "opens the concrete type %s permission editor and retires it on tenant switch",
  async (fileType) => {
    rows = [file(11, { file_type: fileType })];
    const view = mount("workspace");
    fireEvent.click(
      await within(await menu()).findByRole("menuitem", {
        name: "managePermission",
      }),
    );
    expect(
      await screen.findByRole("dialog", { name: "permission-editor" }),
    ).toHaveTextContent(
      `${fileType === 0 ? "folder" : "knowledge_file"}:11:file-11.pdf`,
    );
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    view.update({ ...scope, tenantId: 202, managementTenantId: 202 });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await screen.findByText("file-11.pdf");
    await waitFor(() =>
      expect(mocks.permissions).toHaveBeenCalledWith("knowledge_space", "7", {
        showError: false,
      }),
    );
  },
);

it("edits a single file's current tags after the menu closes", async () => {
  rows = [file(11, { tags: [{ id: 4, name: "Finance" }] })];
  mount("workspace");
  fireEvent.click(
    await within(await menu()).findByRole("menuitem", { name: "editTag" }),
  );
  expect(
    await screen.findByRole("dialog", { name: "tag-editor" }),
  ).toHaveTextContent('[[11],[{"id":4,"name":"Finance"}]]');
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("moves the row independently of the checkbox selection", async () => {
  rows = [file(), file(12)];
  mount("workspace");
  fireEvent.click(
    await screen.findByRole("checkbox", {
      name: "deletion.select file-12.pdf",
    }),
  );
  fireEvent.click(
    await within(await menu()).findByRole("menuitem", { name: "move.title" }),
  );
  expect(
    await screen.findByRole("dialog", { name: "move-editor" }),
  ).toHaveTextContent('[{"id":11,"type":"file"}]');
});

it.each([
  { status: 3 },
  { status: 6 },
  { status: 7 },
  { file_type: 0, has_failed_files: true },
])("retries only the failed row %j", async (extra) => {
  rows = [file(11, extra), file(12)];
  mount("workspace");
  fireEvent.click(
    await screen.findByRole("checkbox", {
      name: "deletion.select file-12.pdf",
    }),
  );
  fireEvent.click(
    await within(await menu()).findByRole("menuitem", { name: "retry" }),
  );
  expect(mocks.batch).toHaveBeenCalledWith({
    spaceId: 7,
    operation: "retry",
    items: [
      {
        id: 11,
        type: extra.file_type === 0 ? "folder" : "file",
        name: "file-11.pdf",
      },
    ],
  });
});

it("withholds privileged row actions without the corresponding server actions", async () => {
  actions = ["visible"];
  rows = [file(11, { status: 3 })];
  mount("workspace");
  const opened = await menu();
  for (const name of [
    "managePermission",
    "editTag",
    "move.title",
    "retry",
    "rename",
  ]) {
    expect(
      within(opened).queryByRole("menuitem", { name }),
    ).not.toBeInTheDocument();
  }
});

it.each([0, 1])("keeps delete but omits reference sources from the row menu for type %s", async (fileType) => {
  actions = ["visible", "delete"];
  rows = [file(11, { file_type: fileType })];
  mount("workspace");
  const opened = await menu();
  expect(await within(opened).findByRole("menuitem", { name: "delete" })).toBeVisible();
  expect(within(opened).queryByRole("menuitem", { name: "deletion.references" })).not.toBeInTheDocument();
});

it.each([0, 1])(
  "hides every mutating batch entry for a visible-only type %s",
  async (fileType) => {
    actions = ["visible"];
    rows = [
      file(11, { file_type: fileType, status: 3, has_failed_files: true }),
    ];
    mount("workspace");
    fireEvent.click(
      await screen.findByRole("checkbox", {
        name: "deletion.select file-11.pdf",
      }),
    );
    await waitFor(() =>
      expect(mocks.permissions).toHaveBeenCalledWith(
        fileType === 0 ? "folder" : "knowledge_file",
        "11",
      ),
    );
    for (const name of [
      "move.title",
      "batch.download",
      "batch.tag",
      "batch.retry",
      "deletion.selected (1)",
      "deletion.references",
    ]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    expect(mocks.batch).not.toHaveBeenCalled();
  },
);

it.each([
  { held: ["download"], shown: "batch.download" },
  { held: ["move"], shown: "move.title" },
  { held: ["delete"], shown: "deletion.selected (1)" },
  { held: ["rename"], shown: "batch.tag" },
])("shows only the batch actions granted by $held", async ({ held, shown }) => {
  actions = ["visible", ...held];
  mount("workspace");
  fireEvent.click(
    await screen.findByRole("checkbox", {
      name: "deletion.select file-11.pdf",
    }),
  );
  expect(await screen.findByRole("button", { name: shown })).toBeVisible();
  for (const name of [
    "move.title",
    "batch.download",
    "batch.tag",
    "deletion.selected (1)",
  ]) {
    if (name !== shown)
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  }
  expect(
    screen.queryByRole("button", { name: "batch.retry" }),
  ).not.toBeInTheDocument();
});

it("allows the permitted part of a mixed selection to reach the existing batch review", async () => {
  rows = [file(), file(12)];
  mocks.permissions.mockImplementation(async (type: string, id: string) => ({
    actions:
      type === "knowledge_space"
        ? rootActions
        : id === "11"
          ? ["visible", "download"]
          : ["visible"],
  }));
  mount("workspace");
  for (const id of [11, 12])
    fireEvent.click(
      await screen.findByRole("checkbox", {
        name: `deletion.select file-${id}.pdf`,
      }),
    );
  fireEvent.click(
    await screen.findByRole("button", { name: "batch.download" }),
  );
  expect(mocks.batch).toHaveBeenCalledWith(
    expect.objectContaining({
      operation: "download",
      items: [
        { id: 11, type: "file", name: "file-11.pdf" },
        { id: 12, type: "file", name: "file-12.pdf" },
      ],
    }),
  );
});

it("hides an empty batch dropdown and ignores permissions returned after a tenant switch", async () => {
  let resolve!: (value: { actions: string[] }) => void;
  const pending = new Promise<{ actions: string[] }>((done) => {
    resolve = done;
  });
  mocks.permissions.mockImplementation((type: string) =>
    type === "knowledge_space" ? Promise.resolve({ actions: [] }) : pending,
  );
  const target = document.createElement("div");
  document.body.append(target);
  try {
    const view = mount("workspace", false, target);
    fireEvent.click(
      await screen.findByRole("checkbox", {
        name: "deletion.select file-11.pdf",
      }),
    );
    await waitFor(() =>
      expect(mocks.permissions).toHaveBeenCalledWith("knowledge_file", "11"),
    );
    expect(
      screen.queryByRole("button", { name: /detail.batch/ }),
    ).not.toBeInTheDocument();
    view.update({ ...scope, tenantId: 202, managementTenantId: 202 });
    await act(async () => {
      resolve({ actions: ["delete", "move", "rename"] });
    });
    expect(
      screen.queryByRole("button", { name: /detail.batch/ }),
    ).not.toBeInTheDocument();
    expect(mocks.batch).not.toHaveBeenCalled();
  } finally {
    target.remove();
  }
});

it("filters the workspace batch dropdown by the selected resource actions", async () => {
  actions = ["visible", "delete"];
  const target = document.createElement("div");
  document.body.append(target);
  try {
    mount("workspace", false, target);
    fireEvent.click(
      await screen.findByRole("checkbox", {
        name: "deletion.select file-11.pdf",
      }),
    );
    fireEvent.keyDown(
      await screen.findByRole("button", { name: "detail.batch" }),
      { key: "Enter" },
    );
    const opened = await screen.findByRole("menu");
    expect(
      within(opened).getByRole("menuitem", { name: "deletion.selected" }),
    ).toBeVisible();
    for (const name of [
      "move.title",
      "batch.download",
      "batch.tag",
      "batch.retry",
    ]) {
      expect(
        within(opened).queryByRole("menuitem", { name }),
      ).not.toBeInTheDocument();
    }
  } finally {
    target.remove();
  }
});

it("opens version management from the badge and keeps the separate similar-document entry", async () => {
  rootActions = ["visible", "edit"];
  rows = [file(11, { has_similar: true, is_multi_version: false })];
  mount("workspace", true);
  fireEvent.click(
    await screen.findByRole("button", {
      name: "knowledge.version.pill_similar",
    }),
  );
  const management = await screen.findByRole("dialog", { name: "version-management" });
  expect(management).toHaveTextContent('[11,"file-11.pdf"]');
  fireEvent.click(within(management).getByRole("button", { name: "close" }));
  const opened = await menu();
  expect(
    await within(opened).findByRole("menuitem", { name: "knowledge.version.dialog_title" }),
  ).toBeVisible();
  expect(
    within(opened).queryByRole("menuitem", { name: "knowledge.version.history.title" }),
  ).not.toBeInTheDocument();
  fireEvent.click(within(opened).getByRole("menuitem", { name: "versions.similar" }));
  expect(await screen.findByRole("dialog", { name: "similar-documents" })).toHaveTextContent("[11]");
});

it("shows version management and history when the permission payload omits the visible relation", async () => {
  actions = ["rename", "move", "manage_permission", "delete", "download"];
  rootActions = ["edit", "manage_permission", "delete"];
  rows = [file(11, { version_no: 2, is_multi_version: true, file_name: "versioned.md" })];
  mount("workspace", true);
  expect(await screen.findByText("V2")).toBeVisible();
  const opened = await menu("versioned.md");
  expect(
    await within(opened).findByRole("menuitem", { name: "knowledge.version.dialog_title" }),
  ).toBeVisible();
  expect(
    within(opened).getByRole("menuitem", { name: "knowledge.version.history.title" }),
  ).toBeVisible();
});

it("shows version numbers and history for multiple versions", async () => {
  rows = [file(11, { version_no: 3, is_multi_version: true })];
  mount("workspace", true);
  expect(await screen.findByText("V3")).toBeVisible();
  fireEvent.click(
    await within(await menu()).findByRole("menuitem", {
      name: "knowledge.version.history.title",
    }),
  );
  expect(
    await screen.findByRole("dialog", { name: "version-history" }),
  ).toHaveTextContent("11");
});

it.each([false, true])(
  "withholds version management without a feature flag or space edit (flag=%s)",
  async (enabled) => {
    rootActions = enabled ? ["visible", "manage_permission"] : ["visible", "edit", "manage_permission"];
    rows = [file(11, { has_similar: true, is_multi_version: false })];
    mount("workspace", enabled);
    const opened = await menu();
    expect(
      within(opened).queryByRole("menuitem", { name: "knowledge.version.dialog_title" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "knowledge.version.pill_similar" }),
    ).not.toBeInTheDocument();
  },
);


it.each([0, 1])("omits reference sources from both batch toolbar variants for type %s", async (fileType) => {
  actions = ["visible", "delete"];
  rows = [file(11, { file_type: fileType })];
  const view = mount("workspace");
  fireEvent.click(await screen.findByRole("checkbox", { name: "deletion.select file-11.pdf" }));
  expect(await screen.findByRole("button", { name: "deletion.selected (1)" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "deletion.references" })).not.toBeInTheDocument();
  view.unmount();

  const target = document.createElement("div");
  document.body.append(target);
  try {
    mount("workspace", false, target);
    fireEvent.click(await screen.findByRole("checkbox", { name: "deletion.select file-11.pdf" }));
    const trigger = await screen.findByRole("button", { name: "detail.batch" });
    fireEvent.keyDown(trigger, { key: "Enter" });
    const opened = await screen.findByRole("menu");
    expect(within(opened).getByRole("menuitem", { name: "deletion.selected" })).toBeVisible();
    expect(within(opened).queryByRole("menuitem", { name: "deletion.references" })).not.toBeInTheDocument();
  } finally {
    target.remove();
  }
});

it.each([true, false])("requires edit instead of permission management for batch similar documents (edit=%s)", async (edit) => {
  rootActions = ["visible", edit ? "edit" : "manage_permission"];
  rows = [file(11, { has_similar: true, is_multi_version: false })];
  mount("workspace", true);
  fireEvent.click(await screen.findByRole("checkbox", { name: "deletion.select file-11.pdf" }));
  await waitFor(() => expect(mocks.permissions).toHaveBeenCalledWith("knowledge_space", "7", expect.anything()));
  const name = "knowledge.version.header_process_similar_label";
  if (edit) {
    fireEvent.click(await screen.findByRole("button", { name }));
    expect(await screen.findByRole("dialog", { name: "similar-documents" })).toHaveTextContent("[11]");
  } else {
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  }
});
