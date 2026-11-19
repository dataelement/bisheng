import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { toast } from "@bisheng/ui";
import { KnowledgeSpaceSidebar } from "@/pages/KnowledgePage/sidebar/KnowledgeSpaceSidebar";
import { SpaceDetail } from "@/pages/KnowledgePage/detail";
import { knowledgeQueryKeys } from "@/controllers/hooks/knowledge";
import { useKnowledgeSpaceDeletion } from "@/store/knowledgeSpaceDeletion";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  permissions: vi.fn(),
  error: vi.fn(),
  copies: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({
  default: { get: mocks.get, post: mocks.post },
  showApiError: mocks.error,
}));
vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: mocks.permissions,
}));
vi.mock("@/controllers/API/knowledgeCopy", () => ({
  listOwnedSpaceCopies: mocks.copies,
}));
vi.mock("@/contexts/userContext", async () => ({
  userContext: (await import("react")).createContext({
    user: { user_id: 7, tenant_id: 101 },
  }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: "en" },
  }),
}));
vi.mock("@/pages/KnowledgePage/components/Files", async () => {
  const { useKnowledgeSpaceChildren } =
    await import("@/controllers/hooks/knowledge");
  return {
    default: function Files({
      scope: current,
      spaceId,
    }: {
      scope: typeof scope;
      spaceId: number;
    }) {
      const query = useKnowledgeSpaceChildren(current, spaceId);
      return <p>{query.data?.data.length ? "file-list" : "loading-files"}</p>;
    },
  };
});
const scope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary" as const,
};
const copy = {
  id: 8,
  name: "Copied space",
  state: 1,
  job_id: "copy-8",
  job_state: "failed",
  phase: "failed",
  failed_count: 1,
  total_count: 1,
  succeeded_count: 0,
  user_id: 7,
};
const clients: QueryClient[] = [];
function mount(sidebar = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  clients.push(client);
  const onDeleted = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        {sidebar && (
          <KnowledgeSpaceSidebar
            scope={scope}
            spaceId={8}
            parentId={null}
            canCopy={false}
            onSelect={vi.fn()}
            onDeleted={onDeleted}
          />
        )}
        <SpaceDetail
          scope={scope}
          spaceId={8}
          parentId={null}
          presentation="workspace"
          onOpenFolder={vi.fn()}
          onDeleted={onDeleted}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { client, onDeleted };
}
async function openDelete(sidebar = false) {
  const info = await screen.findByRole("button", { name: "detail.space_info" });
  const more = sidebar
    ? await screen.findByRole("button", { name: "more Copied space" })
    : await within(info.closest("header")!).findByRole("button", {
        name: "more",
      });
  fireEvent.keyDown(more, { key: "Enter" });
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "deletion.delete_space" }),
  );
  const dialog = within(
    await screen.findByRole("dialog", { name: "deletion.delete_space" }),
  );
  await waitFor(() =>
    expect(
      dialog.getByRole("button", { name: "deletion.confirm" }),
    ).toBeEnabled(),
  );
  return dialog;
}
beforeEach(() => {
  vi.clearAllMocks();
  useKnowledgeSpaceDeletion.setState({ entries: {} });
  mocks.copies.mockResolvedValue([]);
  mocks.permissions.mockResolvedValue({
    actions: ["visible", "delete"],
    sources: [],
  });
  mocks.get.mockImplementation(async (url: string) => {
    if (url.endsWith("/mine"))
      return [{ id: 8, name: "Copied space", state: 1, user_id: 7 }];
    if (url.endsWith("/department") || url.endsWith("/joined")) return [];
    if (url.endsWith("/info")) return { id: 8, name: "Copied space", state: 1 };
    if (url.endsWith("/children"))
      return {
        data: [{ id: 9 }],
        page_size: 40,
        has_more: false,
        next_cursor: null,
      };
    if (url.endsWith("/processing-jobs")) return { data: [], total: 0 };
    throw new Error(`Unexpected read ${url}`);
  });
  mocks.post.mockResolvedValue({
    confirmation_id: "delete-8",
    plan_digest: "digest",
    check_complete: true,
    can_execute: true,
    requires_skip_confirmation: false,
    valid_items: [{ id: 8, type: "space", name: "Copied space" }],
    invalid_items: [],
    impact: {
      file_count: 1,
      source_counts: {},
      restricted_counts: {},
      source_page: { data: [], has_more: false },
    },
  });
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  useKnowledgeSpaceDeletion.setState({ entries: {} });
  vi.restoreAllMocks();
});

it.each([false, true])(
  "keeps deletion mounted and pauses the target while the acknowledgement is delayed, sidebar=%s",
  async (sidebar) => {
    const shown = vi.spyOn(toast, "show");
    const { client, onDeleted } = mount(sidebar);
    expect(await screen.findByText("file-list")).toBeVisible();
    const dialog = await openDelete(sidebar);
    let resolve!: (value: unknown) => void;
    mocks.post.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    fireEvent.click(dialog.getByRole("button", { name: "deletion.confirm" }));
    await waitFor(() =>
      expect(
        dialog.getByRole("button", { name: "deletion.status" }),
      ).toBeDisabled(),
    );
    expect(screen.queryByText("file-list")).toBeNull();
    mocks.get.mockClear();
    mocks.permissions.mockClear();
    await act(async () => {
      await client.invalidateQueries({
        queryKey: knowledgeQueryKeys.scope(scope),
      });
    });
    expect(
      mocks.get.mock.calls.filter(([url]) =>
        /\/(info|children|parent|processing-jobs)$/.test(String(url)),
      ),
    ).toHaveLength(0);
    expect(mocks.permissions).not.toHaveBeenCalled();
    expect(onDeleted).not.toHaveBeenCalled();
    expect(shown).not.toHaveBeenCalled();
    await act(async () => {
      resolve({ job_id: "delete-8", state: "succeeded" });
    });
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(8));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mocks.error).not.toHaveBeenCalled();
  },
);

it("does not report success or refetch the missing resource when a failed copy disappears", async () => {
  const shown = vi.spyOn(toast, "show");
  mocks.copies.mockResolvedValue([copy]);
  const read = mocks.get.getMockImplementation()!;
  mocks.get.mockImplementation((url: string) => {
    if (url.endsWith("/processing-jobs/copy-8"))
      return {
        id: "copy-8",
        state: "failed",
        failed_count: 1,
        succeeded_count: 0,
        total_count: 1,
      };
    if (url.endsWith("/processing-jobs/copy-8/items"))
      return { data: [], total: 0 };
    return read(url);
  });
  const { client } = mount();
  expect(await screen.findByText("file-list")).toBeVisible();
  await waitFor(() =>
    expect(
      client.getQueryData([...knowledgeQueryKeys.scope(scope), "copy-tasks"]),
    ).toEqual([copy]),
  );
  mocks.get.mockClear();
  mocks.permissions.mockClear();
  await act(async () => {
    client.setQueryData([...knowledgeQueryKeys.scope(scope), "copy-tasks"], []);
  });
  expect(shown).not.toHaveBeenCalled();
  expect(
    mocks.get.mock.calls.some(([url]) =>
      /\/(info|children)$/.test(String(url)),
    ),
  ).toBe(false);
  expect(mocks.permissions).not.toHaveBeenCalled();
});
