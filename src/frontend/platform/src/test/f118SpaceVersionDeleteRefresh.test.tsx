import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { locationContext } from "@/contexts/locationContext";
import type { SpaceVersionHistory } from "@/controllers/API/knowledgeVersions";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { SpaceVersionHistorySheet } from "@/pages/KnowledgePage/components/SpaceVersionHistorySheet";

const requests = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), error: vi.fn() }));
vi.mock("@/controllers/request", () => ({
  default: { get: requests.get, post: requests.post },
  showApiError: requests.error,
}));

const scope: KnowledgeQueryScope = { identityKey: "user7", tenantId: 1, managementTenantId: 1, view: "admin" };
const history = (): SpaceVersionHistory => ({
  document_id: 41, knowledge_id: 7, title: "Report", doc_code: null, current_primary_version_no: 1,
  versions: [11, 12, 13].map((id, index) => ({
    version_id: id + 40, version_no: index + 1, knowledge_file_id: id, is_primary: id === 11,
    original_file_name: id === 13 ? "deleted.md" : `kept-${id}.md`, file_code: null,
    uploader_name: null, uploader_id: null, upload_time: null, status: 2,
  })),
});
const clients: QueryClient[] = [];

function mount(getHistory: () => Promise<SpaceVersionHistory>, remove: () => Promise<unknown>) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <locationContext.Provider value={{ appConfig: { versionManagementEnabled: true } } as React.ContextType<typeof locationContext>}>
        <SpaceVersionHistorySheet scope={scope} spaceId={7} parentId={null} fileId={11} open
          onOpenChange={vi.fn()} api={{ getSpaceFileVersions: getHistory, deleteSpaceFileVersion: remove }} />
      </locationContext.Provider>
    </QueryClientProvider>,
  );
  return client;
}

async function deleteHistoricalVersion() {
  const row = (await screen.findByText("deleted.md")).closest("tr")!;
  fireEvent.click(await within(row).findByRole("button", { name: "history.actions.delete" }));
  const confirmation = await screen.findByRole("alertdialog");
  await act(async () => { fireEvent.click(within(confirmation).getByRole("button", { name: "confirm" })); });
}

beforeEach(() => {
  vi.resetAllMocks();
  requests.get.mockResolvedValue({ actions: ["visible", "edit", "delete"] });
  requests.post.mockResolvedValue({ check_complete: true, valid_items: [] });
});
afterEach(() => {
  cleanup();
  clients.forEach(client => client.clear());
  clients.length = 0;
});

it.each([false, true])("does not recheck a deleted version while history refresh is slow (stale response: %s)", async stale => {
  let deleted = false;
  let resolve!: (value: SpaceVersionHistory) => void;
  const refreshed = new Promise<SpaceVersionHistory>(done => { resolve = done; });
  const read = vi.fn().mockResolvedValueOnce(history()).mockReturnValue(refreshed);
  const obsoleteRequests: string[] = [];
  requests.get.mockImplementation(async (url: string) => {
    if (deleted && url.includes("knowledge_file/13/")) {
      obsoleteRequests.push(url);
      throw { status_code: 25022 };
    }
    return { actions: ["visible", "edit", "delete"] };
  });
  requests.post.mockImplementation(async (url: string, payload: { items: { id: number }[] }) => {
    if (deleted && payload.items.some(item => item.id === 13)) {
      obsoleteRequests.push(url);
      throw { status_code: 25022 };
    }
    return { check_complete: true, valid_items: [] };
  });
  const remove = vi.fn().mockImplementation(async () => { deleted = true; });
  const client = mount(read, remove);
  await deleteHistoricalVersion();
  await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
  expect(screen.queryByText("deleted.md")).not.toBeInTheDocument();
  expect(screen.getByText("kept-11.md")).toBeVisible();
  expect(obsoleteRequests).toEqual([]);
  const next = history();
  if (!stale) next.versions = next.versions.filter(version => version.knowledge_file_id !== 13);
  await act(async () => { resolve(next); });
  await waitFor(() => expect(client.isFetching()).toBe(0));
  expect(screen.queryByText("deleted.md")).not.toBeInTheDocument();
  expect(screen.getByText("kept-12.md")).toBeVisible();
  expect(obsoleteRequests).toEqual([]);
  expect(requests.error).not.toHaveBeenCalled();
  expect(remove).toHaveBeenCalledExactlyOnceWith(53, expect.any(AbortSignal));
});

it("preserves real deletion failures and the unchanged history", async () => {
  const error = { status_code: 25008 };
  const read = vi.fn().mockResolvedValue(history());
  const remove = vi.fn().mockRejectedValue(error);
  mount(read, remove);
  await deleteHistoricalVersion();
  await waitFor(() => expect(requests.error).toHaveBeenCalledWith(error));
  expect(screen.getByText("deleted.md")).toBeVisible();
  expect(read).toHaveBeenCalledTimes(1);
});

it("aborts an in-flight permission read once deletion commits", async () => {
  let pending = false;
  let commit!: () => void;
  let permissionSignal: AbortSignal | undefined;
  let finishPermission!: () => void;
  const permission = new Promise<void>(resolve => { finishPermission = resolve; });
  requests.get.mockImplementation(async (url: string, config?: { signal?: AbortSignal }) => {
    if (pending && url.includes("knowledge_file/13/")) {
      permissionSignal = config?.signal;
      await permission;
    }
    return { actions: ["visible", "edit", "delete"] };
  });
  const read = vi.fn().mockResolvedValue(history());
  const remove = vi.fn().mockReturnValue(new Promise<void>(resolve => { commit = resolve; }));
  const client = mount(read, remove);
  await deleteHistoricalVersion();
  pending = true;
  let refreshing!: Promise<void>;
  await act(async () => {
    refreshing = client.refetchQueries({ predicate: query => query.queryKey.includes("version-delete-actions") && query.queryKey.includes(13) });
  });
  expect(permissionSignal?.aborted).toBe(false);
  await act(async () => { commit(); });
  await waitFor(() => expect(permissionSignal?.aborted).toBe(true));
  await act(async () => { finishPermission(); await refreshing; });
  expect(screen.queryByText("deleted.md")).not.toBeInTheDocument();
  expect(requests.error).not.toHaveBeenCalled();
});

it("continues to surface an unrelated surviving file's permission error", async () => {
  let deleted = false;
  const error = { status_code: 25008 };
  requests.get.mockImplementation(async (url: string) => {
    if (deleted && url.includes("knowledge_file/12/")) throw error;
    return { actions: ["visible", "edit", "delete"] };
  });
  const read = vi.fn().mockImplementation(async () => {
    const data = history();
    if (deleted) data.versions = data.versions.filter(version => version.knowledge_file_id !== 13);
    return data;
  });
  const remove = vi.fn().mockImplementation(async () => { deleted = true; });
  mount(read, remove);
  await deleteHistoricalVersion();
  await waitFor(() => expect(requests.error).toHaveBeenCalledWith(error));
  expect(screen.queryByText("deleted.md")).not.toBeInTheDocument();
});
