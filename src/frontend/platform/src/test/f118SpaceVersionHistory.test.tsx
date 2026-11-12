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
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpaceVersionHistorySheet } from "@/pages/KnowledgePage/components/SpaceVersionHistorySheet";
import type { SpaceVersionHistory } from "@/controllers/API/knowledgeVersions";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";

const mocks = vi.hoisted(() => ({ error: vi.fn() }));
vi.mock("@/controllers/request", () => ({
  default: { get: vi.fn() },
  showApiError: mocks.error,
}));
// Advanced processing tools have their own entry tests; keep history reads isolated.
vi.mock("@/pages/KnowledgePage/components/SpaceFileTools", () => ({
  SpaceFileTools: () => null,
}));
const scope: KnowledgeQueryScope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary",
};
const history = (
  title = "Visible history",
  primary: number | null = null,
): SpaceVersionHistory => ({
  document_id: 41,
  knowledge_id: 7,
  title,
  doc_code: null,
  current_primary_version_no: primary,
  versions: [
    {
      version_id: 51,
      version_no: 3,
      is_primary: false,
      knowledge_file_id: 11,
      original_file_name: "visible.md",
      file_code: null,
      uploader_name: null,
      uploader_id: null,
      upload_time: null,
      status: null,
    },
  ],
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const clients: QueryClient[] = [];
type Props = React.ComponentProps<typeof SpaceVersionHistorySheet>;
function mount(overrides: Partial<Props> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
  });
  clients.push(client);
  const read = vi.fn().mockResolvedValue(history());
  const props: Props = {
    scope,
    spaceId: 7,
    parentId: 9,
    fileId: 11,
    open: true,
    onOpenChange: vi.fn(),
    api: { getSpaceFileVersions: read },
    ...overrides,
  };
  const view = (value: Props) => (
    <QueryClientProvider client={client}>
      <SpaceVersionHistorySheet {...value} />
    </QueryClientProvider>
  );
  const result = render(view(props));
  return {
    ...result,
    client,
    read,
    props,
    update: (next: Partial<Props>) => {
      Object.assign(props, next);
      result.rerender(view({ ...props }));
    },
  };
}
beforeEach(() => vi.clearAllMocks());
afterEach(() => {
  cleanup();
  clients.forEach((client) => client.clear());
  clients.length = 0;
});

it("renders only actual visible history facts without synthesizing hidden primary or nullable metadata", async () => {
  const view = mount();
  const dialog = await screen.findByRole("dialog");
  expect(await within(dialog).findByText("Visible history")).toBeVisible();
  expect(within(dialog).getByText("visible.md")).toBeVisible();
  expect(
    within(dialog).queryByText("f118.primary_version"),
  ).not.toBeInTheDocument();
  expect(within(dialog).getAllByText("--").length).toBeGreaterThanOrEqual(4);
  expect(view.read).toHaveBeenCalledExactlyOnceWith(
    11,
    expect.any(AbortSignal),
  );
  expect(
    within(dialog).queryByRole("button", {
      name: /delete|download|preview|setPrimary/,
    }),
  ).not.toBeInTheDocument();
});

it("keeps actual primary, uploader and document codes when the server makes them visible", async () => {
  const data = history("Current title", 3);
  data.doc_code = "DOC-41";
  Object.assign(data.versions[0], {
    is_primary: true,
    file_code: "FILE-11",
    uploader_name: "Actual user",
    uploader_id: 7,
    upload_time: "2026-11-07T12:00:00",
    status: 2,
  });
  mount({ api: { getSpaceFileVersions: vi.fn().mockResolvedValue(data) } });
  expect(await screen.findByText("DOC-41")).toBeVisible();
  expect(screen.getByText("FILE-11")).toBeVisible();
  expect(screen.getByText("Actual user")).toBeVisible();
  expect(screen.getAllByText("f118.primary_version").length).toBeGreaterThan(0);
});

it("renders an empty visible list without filling it from old row data", async () => {
  const data = history();
  data.versions = [];
  mount({ api: { getSpaceFileVersions: vi.fn().mockResolvedValue(data) } });
  expect(await screen.findByText("f118.no_visible_versions")).toBeVisible();
  expect(screen.queryByText("visible.md")).not.toBeInTheDocument();
});

it("keeps the same ApiError and retries through the original read port", async () => {
  const error = { status_code: 19000, status_message: "denied", handled: true };
  const read = vi
    .fn()
    .mockRejectedValueOnce(error)
    .mockResolvedValue(history("Recovered"));
  mount({ api: { getSpaceFileVersions: read } });
  fireEvent.click(await screen.findByRole("button", { name: "retry" }));
  expect(await screen.findByText("Recovered")).toBeVisible();
  expect(mocks.error).toHaveBeenCalledWith(error);
  expect(read).toHaveBeenCalledTimes(2);
});

it("hides retained data after a failed refetch", async () => {
  const read = vi
    .fn()
    .mockResolvedValueOnce(history("Retired title"))
    .mockRejectedValue({ status_code: 19000 });
  const view = mount({ api: { getSpaceFileVersions: read } });
  await screen.findByText("Retired title");
  await act(() => view.client.invalidateQueries());
  expect(await screen.findByRole("button", { name: "retry" })).toBeVisible();
  expect(screen.queryByText("Retired title")).not.toBeInTheDocument();
  expect(screen.queryByText("visible.md")).not.toBeInTheDocument();
});

it.each([
  "identityKey",
  "tenantId",
  "managementTenantId",
  "view",
  "spaceId",
  "parentId",
  "fileId",
] as const)(
  "permanently retires pending scope/target ABA: %s",
  async (field) => {
    const old = deferred<SpaceVersionHistory>();
    const read = vi
      .fn()
      .mockReturnValueOnce(old.promise)
      .mockResolvedValue(history("Fresh history"));
    const view = mount({ api: { getSpaceFileVersions: read } });
    await waitFor(() => expect(read).toHaveBeenCalledTimes(1));
    const signal: AbortSignal = read.mock.calls[0][1];
    if (field === "spaceId" || field === "parentId" || field === "fileId") {
      view.update({ [field]: field === "spaceId" ? 8 : 12 });
    } else {
      view.update({
        scope: {
          ...scope,
          [field]:
            field === "identityKey"
              ? "user:8"
              : field === "view"
                ? "admin"
                : 202,
        },
      });
    }
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
    expect(signal.aborted).toBe(true);
    view.update({ scope, spaceId: 7, parentId: 9, fileId: 11 });
    await waitFor(() => expect(read).toHaveBeenCalledTimes(3));
    await act(async () => old.resolve(history("Old secret")));
    expect(await screen.findByText("Fresh history")).toBeVisible();
    expect(screen.queryByText("Old secret")).not.toBeInTheDocument();
    expect(view.props.onOpenChange).not.toHaveBeenCalled();
  },
);

it("starts no GET while closed and creates a fresh request after close/reopen", async () => {
  const old = deferred<SpaceVersionHistory>();
  const read = vi
    .fn()
    .mockReturnValueOnce(old.promise)
    .mockResolvedValue(history("New opening"));
  const view = mount({ open: false, api: { getSpaceFileVersions: read } });
  expect(read).not.toHaveBeenCalled();
  view.update({ open: true });
  await waitFor(() => expect(read).toHaveBeenCalledTimes(1));
  const signal: AbortSignal = read.mock.calls[0][1];
  view.update({ open: false });
  expect(signal.aborted).toBe(true);
  view.update({ open: true });
  expect(await screen.findByText("New opening")).toBeVisible();
  await act(async () => old.resolve(history("Closed secret")));
  expect(screen.queryByText("Closed secret")).not.toBeInTheDocument();
  expect(read).toHaveBeenCalledTimes(2);
});

it("unmount cancels only this opening, preserving a concurrent reader", async () => {
  const first = deferred<SpaceVersionHistory>();
  const second = deferred<SpaceVersionHistory>();
  const read = vi
    .fn()
    .mockReturnValueOnce(first.promise)
    .mockReturnValueOnce(second.promise);
  const a = mount({ api: { getSpaceFileVersions: read } });
  render(
    <QueryClientProvider client={a.client}>
      <SpaceVersionHistorySheet {...a.props} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
  const one: AbortSignal = read.mock.calls[0][1];
  const two: AbortSignal = read.mock.calls[1][1];
  a.unmount();
  expect(one.aborted).toBe(true);
  expect(two.aborted).toBe(false);
  await act(async () => second.resolve(history("Other reader")));
  expect(await screen.findByText("Other reader")).toBeVisible();
});

it("notifies the controlled parent only for an explicit close", async () => {
  const view = mount();
  await screen.findByText("Visible history");
  fireEvent.click(screen.getByRole("button", { name: "close" }));
  expect(view.props.onOpenChange).toHaveBeenCalledExactlyOnceWith(false);
});
