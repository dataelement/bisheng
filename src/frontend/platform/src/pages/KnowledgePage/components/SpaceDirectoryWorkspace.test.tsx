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
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { page, row } from "@/test/helpers/knowledgeSpaceFixtures";
import Files, { type FilesProps } from "./Files";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  permissions: vi.fn(),
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
vi.mock("./SpaceVersionHistorySheet", () => ({
  SpaceVersionHistorySheet: () => null,
}));
vi.mock("./PreviewFile", () => ({
  default: () => <span>preview-content</span>,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: "en", loadNamespaces: vi.fn() },
  }),
}));

const scope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary" as const,
};
const rows = [
  {
    id: 9,
    knowledge_id: 7,
    file_type: 0,
    file_name: "Folder",
    update_time: "2026-11-12T10:00:00",
  },
  {
    id: 11,
    knowledge_id: 7,
    file_type: 1,
    file_name: "report.pdf",
    status: 2,
    file_size: 2048,
    update_time: "2026-11-12T10:00:00",
    tags: [{ id: 1, name: "Finance" }],
  },
];
const clients: QueryClient[] = [];
function mount(props: Partial<FilesProps> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
  });
  clients.push(client);
  const onOpenFolder = vi.fn();
  const draw = (next: Partial<FilesProps>) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Files
          scope={scope}
          spaceId={7}
          presentation="workspace"
          onOpenFolder={onOpenFolder}
          {...next}
        />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const view = render(draw(props));
  return {
    ...view,
    onOpenFolder,
    update: (next: Partial<FilesProps>) => view.rerender(draw(next)),
  };
}

function mockScrollIntersections() {
  class ScrollObserver {
    observe = vi.fn<(target: Element) => void>();
    disconnect = vi.fn();

    constructor(
      private readonly callback: IntersectionObserverCallback,
      readonly options: IntersectionObserverInit,
    ) {
      observers.push(this);
    }

    intersect(isIntersecting = true) {
      const target = this.observe.mock.lastCall?.[0];
      this.callback(
        [{ target, isIntersecting } as IntersectionObserverEntry],
        this as unknown as IntersectionObserver,
      );
    }
  }

  const observers: ScrollObserver[] = [];
  vi.stubGlobal("IntersectionObserver", ScrollObserver);
  return observers;
}

beforeEach(() => {
  vi.clearAllMocks();
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      values.set(key, value);
    }),
    removeItem: vi.fn((key: string) => {
      values.delete(key);
    }),
    clear: vi.fn(() => values.clear()),
  });
  mocks.permissions.mockResolvedValue({ actions: ["visible"] });
  mocks.post.mockImplementation(async (url: string) => {
    if (url.endsWith("/batch/download/inspect")) return {
      can_execute: false, check_complete: true, valid_items: [],
      invalid_items: [{ id: 11, type: "file", reason: "permission_denied" }],
    };
    throw new Error(`Unexpected write ${url}`);
  });
  mocks.get.mockImplementation(
    async (url: string, options?: { params?: { page?: number } }) => {
      if (url.endsWith("/children"))
        return {
          data: rows,
          page_size: 40,
          has_more: false,
          next_cursor: null,
        };
      if (url.endsWith("/search"))
        return {
          data: rows,
          page_size: 40,
          page: options?.params?.page ?? 1,
          has_more: false,
        };
      if (url.endsWith("/preview"))
        return {
          original_url: "https://objects.test/report.pdf",
          preview_url: "https://objects.test/preview.pdf",
        };
      throw new Error(`Unexpected read ${url}`);
    },
  );
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("retains the workspace view across folder remounts and isolates identity and tenant preferences", async () => {
  const view = mount();
  await screen.findByText("report.pdf");
  fireEvent.click(screen.getByRole("button", { name: "workspace.card_view" }));
  view.update({ parentId: 9 });
  await screen.findByText("report.pdf");
  expect(view.container.querySelector('[data-view-mode="card"]')).toBeTruthy();
  view.update({ parentId: 10 });
  await screen.findByText("report.pdf");
  expect(view.container.querySelector('[data-view-mode="card"]')).toBeTruthy();
  view.update({ scope: { ...scope, identityKey: "user:8" } });
  await screen.findByText("report.pdf");
  expect(view.container.querySelector('[data-view-mode="list"]')).toBeTruthy();
  view.update({ scope: { ...scope, tenantId: 102, managementTenantId: 102 } });
  await screen.findByText("report.pdf");
  expect(view.container.querySelector('[data-view-mode="list"]')).toBeTruthy();
  view.update({ parentId: 9 });
  await screen.findByText("report.pdf");
  expect(view.container.querySelector('[data-view-mode="card"]')).toBeTruthy();
});

it("ignores unsupported saved view values and tolerates restricted preference storage", async () => {
  const get = vi
    .spyOn(window.localStorage, "getItem")
    .mockReturnValue("unsupported");
  const view = mount();
  await screen.findByText("report.pdf");
  expect(view.container.querySelector('[data-view-mode="list"]')).toBeTruthy();
  get.mockImplementation(() => {
    throw new Error("Storage unavailable");
  });
  vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
    throw new Error("Storage unavailable");
  });
  view.update({ parentId: 9 });
  await screen.findByText("report.pdf");
  expect(view.container.querySelector('[data-view-mode="list"]')).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "workspace.card_view" }));
  expect(view.container.querySelector('[data-view-mode="card"]')).toBeTruthy();
});

it("keeps the ordinary table presentation independent from workspace preferences", async () => {
  const get = vi.spyOn(window.localStorage, "getItem");
  mount({ presentation: undefined });
  await screen.findByText("report.pdf");
  expect(screen.getByRole("table")).toBeVisible();
  expect(
    get.mock.calls.some(([key]) => key.startsWith("knowledge-view-mode:")),
  ).toBe(false);
});

it("uses parsed-file thumbnails in list and card views and falls back to file icons after a broken image", async () => {
  mocks.get.mockResolvedValue({
    data: [
      { ...rows[1], thumbnails: "https://objects.test/report-thumb.png" },
      {
        ...rows[1],
        id: 12,
        file_name: "notes.txt",
        thumbnails: "https://objects.test/text-thumb.png",
      },
      {
        ...rows[1],
        id: 13,
        file_name: "pending.pdf",
        status: 4,
        thumbnails: "https://objects.test/pending-thumb.png",
      },
    ],
    page_size: 40,
    has_more: false,
    next_cursor: null,
  });
  const view = mount();
  await screen.findByText("report.pdf");
  expect(view.container.querySelectorAll("img")).toHaveLength(1);
  expect(view.container.querySelector("img")).toHaveAttribute(
    "src",
    "https://objects.test/report-thumb.png",
  );
  fireEvent.click(screen.getByRole("button", { name: "workspace.card_view" }));
  const image = view.container.querySelector("img");
  expect(image).toHaveClass("object-cover", "object-top");
  fireEvent.error(image!);
  expect(view.container.querySelector("img")).toBeNull();
  expect(screen.getAllByRole("button", { name: "report.pdf" })).toHaveLength(2);
});

it("restores list and card presentations without losing folder navigation, file selection or preview", async () => {
  const view = mount();
  fireEvent.click(await screen.findByRole("button", { name: "Folder" }));
  expect(view.onOpenFolder).toHaveBeenCalledWith(9);
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.getAllByText("2026-11-12")).toHaveLength(2);
  expect(screen.queryByText("2.0 KB")).toBeNull();
  expect(screen.getByText("#Finance")).toBeVisible();
  fireEvent.click(
    screen.getByRole("checkbox", { name: "workspace.select_all" }),
  );
  expect(
    screen.getByRole("checkbox", { name: "deletion.select report.pdf" }),
  ).toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "workspace.card_view" }));
  expect(view.container.querySelector('[data-view-mode="card"]')).toBeTruthy();
  expect(
    screen.getByRole("checkbox", { name: "deletion.select report.pdf" }),
  ).toBeChecked();
  fireEvent.click(screen.getAllByRole("button", { name: "report.pdf" })[0]);
  await screen.findByText("preview-content");
});

it("shows header batch actions only while directory items are selected", async () => {
  mocks.permissions.mockResolvedValue({ actions: ["visible", "move"] });
  const toolbarTarget = document.createElement("div");
  document.body.append(toolbarTarget);
  try {
    mount({ toolbarTarget });
    const file = await screen.findByRole("checkbox", { name: "deletion.select report.pdf" });
    const folder = screen.getByRole("checkbox", { name: "deletion.select Folder" });
    const toolbar = within(toolbarTarget);

    expect(toolbar.queryByRole("button", { name: "detail.batch" })).toBeNull();
    fireEvent.click(folder);
    expect(await toolbar.findByRole("button", { name: "detail.batch" })).toBeVisible();
    fireEvent.click(file);
    expect(await toolbar.findByRole("button", { name: "detail.batch" })).toBeVisible();
    fireEvent.click(folder);
    fireEvent.click(file);
    expect(toolbar.queryByRole("button", { name: "detail.batch" })).toBeNull();
  } finally {
    toolbarTarget.remove();
  }
});

it.each(["workspace", undefined] as const)("hides unavailable batch and download actions for manage-permission-only users in %s presentation", async (presentation) => {
  mocks.permissions.mockResolvedValue({ actions: ["visible", "manage_permission"] });
  const view = mount({ presentation });
  fireEvent.click(await screen.findByRole("checkbox", { name: "deletion.select report.pdf" }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalledWith(
    "/api/v1/knowledge/space/7/files/batch/download/inspect",
    { items: [{ id: 11, type: "file" }] },
  ));
  await waitFor(() => expect(mocks.permissions.mock.calls.some(([kind, id]) => kind === "knowledge_file" && id === "11")).toBe(true));
  expect(screen.queryByRole("button", { name: "detail.batch" })).not.toBeInTheDocument();
  expect(view.container.querySelector('[aria-label="downloadOriginal"]')).toBeNull();
  fireEvent.keyDown(screen.getByRole("button", { name: "more report.pdf" }), { key: "ArrowDown" });
  expect(await screen.findByRole("menuitem", { name: "managePermission" })).toBeVisible();
  for (const name of ["downloadOriginal", "editTag", "rename", "move", "delete"]) {
    expect(screen.queryByRole("menuitem", { name })).not.toBeInTheDocument();
  }
});

it("appends directory pages on scroll, including continuation after an empty page", async () => {
  const observers = mockScrollIntersections();
  let finishEmptyPage!: () => void;
  const pendingPage = new Promise<void>((resolve) => { finishEmptyPage = resolve; });
  mocks.get.mockImplementation(async (_url, { params }) => {
    if (params.cursor === "empty/+==") {
      await pendingPage;
      return page([], "remaining/+==");
    }
    if (params.cursor === "remaining/+==") return page([row(12, "next.pdf")]);
    return page([row()], "empty/+==");
  });

  const view = mount();
  const selected = await screen.findByRole("checkbox", { name: "deletion.select report.pdf" });
  fireEvent.click(selected);
  expect(screen.queryByRole("button", { name: "f118.more_files" })).toBeNull();
  await waitFor(() => expect(observers.at(-1)?.observe).toHaveBeenCalled());
  const first = observers.at(-1)!;
  expect(first.options.root).toBe(view.container.querySelector("[data-view-mode]")?.parentElement);
  expect(first.options.rootMargin).toBe("0px 0px 240px 0px");

  act(() => first.intersect(false));
  expect(mocks.get).toHaveBeenCalledTimes(1);
  act(() => {
    first.intersect();
    first.intersect();
  });
  expect(mocks.get).toHaveBeenCalledTimes(2);

  finishEmptyPage();
  await waitFor(() => expect(observers.at(-1)).not.toBe(first));
  const next = observers.at(-1)!;
  act(() => next.intersect());
  await screen.findByText("next.pdf");

  expect(screen.getByRole("checkbox", { name: "deletion.select report.pdf" })).toBeChecked();
  expect(mocks.get.mock.calls.map(([, { params }]) => params.cursor)).toEqual([
    undefined,
    "empty/+==",
    "remaining/+==",
  ]);
  expect(next.disconnect).toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "f118.more_files" })).toBeNull();
});

it.each(["an error", "a repeated cursor"])("pauses automatic loading after %s and retries the same cursor", async (failure) => {
  const observers = mockScrollIntersections();
  let failed = false;
  mocks.get.mockImplementation(async (_url, { params }) => {
    if (!params.cursor) return page([row()], "retry/+==");
    if (!failed) {
      failed = true;
      if (failure === "a repeated cursor") return page([row()], "retry/+==");
      throw new Error("next page failed");
    }
    return page([row(12, "next.pdf")]);
  });

  mount({ scope: { ...scope, view: "admin" } });
  await screen.findByText("report.pdf");
  fireEvent.click(screen.getByRole("button", { name: "workspace.card_view" }));
  await waitFor(() => expect(observers.at(-1)?.observe).toHaveBeenCalled());
  const observer = observers.at(-1)!;
  act(() => observer.intersect());
  const retry = await screen.findByRole("button", { name: "retry" });
  expect(screen.getByText("report.pdf")).toBeVisible();
  expect(observer.disconnect).toHaveBeenCalled();
  act(() => observer.intersect());
  expect(mocks.get).toHaveBeenCalledTimes(2);

  fireEvent.click(retry);
  await screen.findByText("next.pdf");
  expect(mocks.get.mock.calls.map(([, { params }]) => params.cursor)).toEqual([
    undefined,
    "retry/+==",
    "retry/+==",
  ]);
});

it("sends sort changes to the directory and search APIs and resets the cursor", async () => {
  mount();
  await screen.findByText("report.pdf");
  expect(mocks.get).toHaveBeenCalledWith("/api/v1/knowledge/space/7/children", {
    params: expect.objectContaining({
      order_field: "file_type",
      order_sort: "asc",
    }),
    paramsSerializer: { indexes: null },
  });
  fireEvent.keyDown(screen.getByRole("button", { name: "workspace.sort" }), {
    key: "Enter",
  });
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "workspace.sort_name" }),
  );
  await waitFor(() =>
    expect(mocks.get).toHaveBeenLastCalledWith(
      "/api/v1/knowledge/space/7/children",
      {
        params: expect.objectContaining({
          order_field: "file_name",
          order_sort: "asc",
        }),
        paramsSerializer: { indexes: null },
      },
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "search" }));
  const search = screen.getByPlaceholderText("searchFileName");
  expect(search).toHaveFocus();
  fireEvent.change(search, {
    target: { value: "report" },
  });
  await waitFor(() =>
    expect(mocks.get).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/7/search",
      expect.objectContaining({
        params: expect.objectContaining({
          keyword: "report",
          page: 1,
          order_field: "file_name",
          order_sort: "asc",
        }),
      }),
    ),
  );
});

it.each([
  ["list", "Folder"],
  ["list", "report.pdf"],
  ["card", "Folder"],
  ["card", "report.pdf"],
])("labels the %s row deletion as Delete for %s", async (layout, name) => {
  mocks.permissions.mockResolvedValue({ actions: ["visible", "delete"] });
  mount();
  await screen.findByRole("button", { name: "report.pdf" });
  if (layout === "card")
    fireEvent.click(
      screen.getByRole("button", { name: "workspace.card_view" }),
    );
  fireEvent.keyDown(screen.getByRole("button", { name: `more ${name}` }), {
    key: "ArrowDown",
  });
  expect(await screen.findByRole("menuitem", { name: "delete" })).toBeVisible();
  expect(
    screen.queryByRole("menuitem", { name: "deletion.delete_items" }),
  ).toBeNull();
});
