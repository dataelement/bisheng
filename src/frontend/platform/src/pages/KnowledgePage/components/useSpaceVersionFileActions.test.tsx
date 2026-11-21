import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { useSpaceVersionFileActions } from "./useSpaceVersionFileActions";

const mocks = vi.hoisted(() => ({ inspect: vi.fn(), download: vi.fn(), error: vi.fn() }));
vi.mock("@/controllers/API/knowledgeBatch", () => ({ inspectBatchItems: mocks.inspect }));
vi.mock("@/controllers/API/knowledgeFiles", () => ({
  knowledgeFilesApi: { getSpaceFileDownload: mocks.download },
}));
vi.mock("@/controllers/request", () => ({ default: {}, showApiError: mocks.error }));

const scope: KnowledgeQueryScope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "admin",
};
const previous = { knowledge_file_id: 11 };
const primary = { knowledge_file_id: 12 };
const clients: QueryClient[] = [];

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  return renderHook(
    () => useSpaceVersionFileActions({ scope, spaceId: 7, parentId: 9, versions: [previous, primary] }),
    { wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> },
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.inspect.mockResolvedValue({ check_complete: true, valid_items: [{ id: 11, type: "file" }] });
  mocks.download.mockResolvedValue({ original_url: "/versions/old.pdf" });
});

afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.restoreAllMocks();
});

it("opens the selected physical version in a new Platform tab with its view and folder", () => {
  const open = vi.spyOn(window, "open").mockReturnValue(null);
  const { result } = mount();
  result.current.onPreview(99);
  result.current.onPreview(11);
  expect(open).toHaveBeenCalledExactlyOnceWith(
    "/filelib/7?file_id=11&view=admin&parent_id=9",
    "_blank",
    "noopener",
  );
});

it("inspects each physical version and downloads only the granted version", async () => {
  const clicked: HTMLAnchorElement[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push(this);
  });
  const { result } = mount();
  const { signal } = new AbortController();
  await waitFor(() => expect(result.current.canDownload(previous)).toBe(true));
  expect(result.current.canDownload(primary)).toBe(false);
  expect(mocks.inspect).toHaveBeenCalledExactlyOnceWith(
    { spaceId: 7, operation: "download", items: [{ id: 11, type: "file" }, { id: 12, type: "file" }] },
    expect.any(AbortSignal),
  );
  await result.current.onDownload(12, "primary.pdf", signal);
  await result.current.onDownload(11, "old.pdf", signal);
  expect(mocks.download).toHaveBeenCalledExactlyOnceWith(7, 11, signal);
  expect(clicked.map((link) => [link.getAttribute("href"), link.download])).toEqual([["/versions/old.pdf", "old.pdf"]]);
});

it("ignores a download response after the history opening has retired", async () => {
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  let resolve!: (response: { original_url: string }) => void;
  mocks.download.mockReturnValue(new Promise((done) => { resolve = done; }));
  const { result } = mount();
  const controller = new AbortController();
  await waitFor(() => expect(result.current.canDownload(previous)).toBe(true));
  const pending = result.current.onDownload(11, "old.pdf", controller.signal);
  controller.abort();
  resolve({ original_url: "/versions/old.pdf" });
  await pending;
  await result.current.onDownload(11, "old.pdf", controller.signal);
  expect(mocks.download).toHaveBeenCalledTimes(1);
  expect(click).not.toHaveBeenCalled();
});
