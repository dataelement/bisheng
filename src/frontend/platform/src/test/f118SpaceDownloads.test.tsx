import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Files from "@/pages/KnowledgePage/components/Files";
import type { BatchInspection } from "@/controllers/API/knowledgeBatch";
import { row, page } from "./helpers/knowledgeSpaceFixtures";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), error: vi.fn() }));
vi.mock("@/controllers/request", () => ({
  default: { get: mocks.get, post: mocks.post },
  showApiError: mocks.error,
}));
vi.mock("@/controllers/API", () => ({}));
vi.mock("@/pages/KnowledgePage/components/PreviewFile", () => ({ default: () => null }));
const clients: QueryClient[] = [];
const allowed = (ids: number[]): BatchInspection => ({
  check_complete: true,
  can_execute: ids.length > 0,
  valid_items: ids.map((id) => ({ id, type: "file" })),
  invalid_items: [],
  requires_skip_confirmation: false,
  impact: {},
});
function deferred() {
  let resolve!: (value: BatchInspection) => void;
  const promise = new Promise<BatchInspection>((done) => { resolve = done; });
  return { promise, resolve };
}
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
  });
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Files spaceId={7} scope={{ identityKey: "user:7", tenantId: 101, managementTenantId: 101, view: "ordinary" }} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
const downloadButton = () => screen.queryByRole("button", { name: "downloadOriginal" });
beforeEach(() => {
  vi.resetAllMocks();
  mocks.get.mockImplementation(async (url: string) =>
    url.endsWith("/children") ? page([row()]) : { actions: [], sources: [], mode: "INHERIT", roster_complete: true },
  );
  mocks.post.mockImplementation(async (url: string) =>
    url.endsWith("/inspect") ? allowed([]) : { allowed: false },
  );
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});

it("keeps rows selectable while a single page download check is pending", async () => {
  const pending = deferred();
  mocks.get.mockImplementation(async (url: string) => url.endsWith("/children")
    ? page([row(), row(12, "denied.pdf"), row(9, "Folder", 0), row(99, "Unknown", 9)])
    : { actions: [] });
  mocks.post.mockImplementation((url: string) => url.endsWith("/inspect") ? pending.promise : Promise.resolve({ allowed: false }));
  mount();
  const checkbox = await screen.findByRole("checkbox", { name: "deletion.select report.pdf" });
  fireEvent.click(checkbox);
  expect(checkbox).toBeChecked();
  expect(downloadButton()).not.toBeInTheDocument();
  await waitFor(() => expect(mocks.post).toHaveBeenCalledWith(
    "/api/v1/knowledge/space/7/files/batch/download/inspect",
    { items: [{ id: 11, type: "file" }, { id: 12, type: "file" }] },
  ));
  await act(async () => pending.resolve(allowed([11])));
  const button = await screen.findByRole("button", { name: "downloadOriginal" });
  expect(within(button.closest("tr")!).getByText("report.pdf")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "downloadOriginal" })).toHaveLength(1);
  expect(checkbox).toBeChecked();
});

it("checks only the newly loaded cursor page and preserves previous download buttons", async () => {
  mocks.get.mockImplementation(async (url: string, options?: { params?: { cursor?: string } }) =>
    url.endsWith("/children")
      ? options?.params?.cursor ? page([row(12, "next.pdf")]) : page([row()], "next-cursor")
      : { actions: [] },
  );
  mocks.post.mockImplementation(async (url: string, body: { items: { id: number }[] }) =>
    url.endsWith("/inspect") ? allowed(body.items.map((item) => item.id)) : { allowed: false },
  );
  mount();
  await screen.findByRole("button", { name: "downloadOriginal" });
  fireEvent.click(screen.getByRole("button", { name: "f118.more_files" }));
  await waitFor(() => expect(screen.getAllByRole("button", { name: "downloadOriginal" })).toHaveLength(2));
  expect(mocks.post.mock.calls.filter(([url]) => url.endsWith("/inspect")).map(([, body]) => body.items)).toEqual([
    [{ id: 11, type: "file" }], [{ id: 12, type: "file" }],
  ]);
});

it("ignores old directory permissions after switching to search with the same file id", async () => {
  const pending = deferred();
  let first = true;
  mocks.post.mockImplementation((url: string) => {
    if (!url.endsWith("/inspect")) return Promise.resolve({ allowed: false });
    if (first) { first = false; return pending.promise; }
    return Promise.resolve(allowed([]));
  });
  mocks.get.mockImplementation(async (url: string) =>
    url.endsWith("/children") ? page([row()]) : url.endsWith("/search")
      ? { data: [row()], page: 1, page_size: 40, has_more: false } : { actions: [] },
  );
  mount();
  await screen.findByText("report.pdf");
  await waitFor(() => expect(mocks.post.mock.calls.some(([url]) => url.endsWith("/inspect"))).toBe(true));
  fireEvent.change(screen.getByPlaceholderText("searchFileName"), { target: { value: "report" } });
  await screen.findByText("report.pdf");
  await act(async () => pending.resolve(allowed([11])));
  expect(downloadButton()).not.toBeInTheDocument();
});

it.each(["failed", "incomplete"])("keeps selection usable when permission checking is %s", async (mode) => {
  const error = new Error("permission lookup unavailable");
  mocks.post.mockImplementation(async (url: string) => {
    if (!url.endsWith("/inspect")) return { allowed: false };
    if (mode === "failed") throw error;
    return { ...allowed([11]), check_complete: false };
  });
  mount();
  const checkbox = await screen.findByRole("checkbox", { name: "deletion.select report.pdf" });
  if (mode === "failed") await waitFor(() => expect(mocks.error).toHaveBeenCalledWith(error));
  fireEvent.click(checkbox);
  expect(checkbox).toBeChecked();
  expect(downloadButton()).not.toBeInTheDocument();
});

it("does not query download permissions for an empty page", async () => {
  mocks.get.mockImplementation(async (url: string) => url.endsWith("/children") ? page([]) : { actions: [] });
  mount();
  await screen.findByText("f118.directory_empty");
  expect(mocks.post).not.toHaveBeenCalled();
});
