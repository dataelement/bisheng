import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import * as api from "~/api/knowledgeProcessing";
import { useSpaceProcessingJobs } from "./useSpaceProcessingJobs";

jest.mock("~/utils", () => ({ generateUUID: () => "fixed-retry-operation" }));
let mockAuth = { user: { id: "7", role: "USER" }, token: "credential-a" };
jest.mock("~/hooks/AuthContext", () => ({ useAuthContext: () => mockAuth }));
jest.mock("~/api/request", () => ({
  showApiError: (error: { kind?: string; httpStatus?: number }) => ({
    kind: error.kind ?? "network",
    httpStatus: error.httpStatus,
  }),
}));
jest.mock("~/api/knowledgeProcessing", () => ({
  ...jest.requireActual("~/api/knowledgeProcessing"),
  listProcessingJobs: jest.fn(),
  getProcessingJob: jest.fn(),
  listProcessingItems: jest.fn(),
  retryProcessingJob: jest.fn(),
}));
const base: api.ProcessingJobRead = {
  id: "actual-job",
  space_id: 3,
  kind: "file_reprocess",
  state: "partial_failed",
  revision: 4,
  accepted_at: "2026-11-10",
  started_at: null,
  finished_at: null,
  total_count: 4,
  succeeded_count: 2,
  failed_count: 1,
  pending_count: 1,
  hidden_item_count: 2,
  retryable: true,
  obsolete_reason: null,
  error_code: null,
};
const clients: QueryClient[] = [];
function setup(props = { id: "3", edit: true }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
    logger: { log: () => undefined, warn: () => undefined, error: () => undefined },
  });
  clients.push(client);
  return renderHook(({ id, edit }) => useSpaceProcessingJobs(id, edit), {
    initialProps: props,
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}
async function details(result: { current: ReturnType<typeof useSpaceProcessingJobs> }) {
  await act(async () => {
    await result.current.show();
  });
  await waitFor(() => expect(result.current.history).toHaveLength(1));
  act(() => result.current.select(result.current.history![0]));
  await waitFor(() => expect(result.current.job?.revision).toBe(4));
  await waitFor(() => expect(result.current.loading).toBe(false));
}
beforeEach(() => {
  jest.clearAllMocks();
  mockAuth = { user: { id: "7", role: "USER" }, token: "credential-a" };
  jest.mocked(api.listProcessingJobs).mockImplementation(async (_id, _query, scope) => {
    scope?.onTenant?.("101");
    return { data: [base], total: 21 };
  });
  jest.mocked(api.getProcessingJob).mockResolvedValue(base);
  jest.mocked(api.listProcessingItems).mockResolvedValue({ data: [], total: 21 });
  jest
    .mocked(api.retryProcessingJob)
    .mockResolvedValue({ job_id: base.id, accepted: true, state: "accepted", reused: false });
});
afterEach(() => clients.splice(0).forEach((client) => client.clear()));

it("does not read task summaries or items without the current Root edit action", async () => {
  const { result } = setup({ id: "3", edit: false });
  await act(async () => {
    await result.current.show();
  });
  expect(result.current.available).toBe(false);
  expect(api.listProcessingJobs).not.toHaveBeenCalled();
  expect(api.listProcessingItems).not.toHaveBeenCalled();
});
it("uses ordinary list and explicitly scoped kind/detail/items pages", async () => {
  const { result } = setup();
  await details(result);
  expect(api.listProcessingJobs).toHaveBeenCalledWith(
    3,
    { page: 1, page_size: 20 },
    expect.objectContaining({ onTenant: expect.any(Function) }),
  );
  expect(api.getProcessingJob).toHaveBeenCalledWith(
    3,
    base.id,
    "file_reprocess",
    expect.objectContaining({ tenant: "101" }),
  );
  act(() => result.current.setItemPage(2));
  await waitFor(() =>
    expect(api.listProcessingItems).toHaveBeenCalledWith(
      3,
      base.id,
      { kind: "file_reprocess", page: 2, page_size: 20 },
      expect.objectContaining({ tenant: "101" }),
    ),
  );
});
it("retains the original key/revision after an unknown ACK even when current reads advance", async () => {
  const { result } = setup();
  await details(result);
  jest.mocked(api.retryProcessingJob).mockRejectedValueOnce(new Error("unknown ACK"));
  await act(async () => {
    await result.current.retry();
  });
  expect(result.current.pending).toBe(true);
  act(() => result.current.close());
  expect(result.current.open).toBe(true);
  const original = jest.mocked(api.retryProcessingJob).mock.calls[0];
  expect(original[2]).toMatchObject({ expected_job_revision: 4 });
  jest
    .mocked(api.getProcessingJob)
    .mockResolvedValue({ ...base, revision: 8, retryable: false, state: "running" });
  await act(async () => {
    await result.current.refresh();
  });
  await act(async () => {
    await result.current.retry();
  });
  expect(jest.mocked(api.retryProcessingJob).mock.calls[1]).toEqual(original);
  expect(result.current.pending).toBe(false);
  expect(result.current.accepted).toBe(true);
  expect(result.current.job?.state).toBe("running");
});
it("retires old tenant and current-credential reads instead of restoring cached state", async () => {
  let resolve!: (value: api.PageData<api.ProcessingJobRead>) => void;
  jest.mocked(api.listProcessingJobs).mockImplementation((_id, _query, scope) => {
    scope?.onTenant?.("101");
    return new Promise((yes) => {
      resolve = yes;
    });
  });
  const { result, rerender } = setup();
  let pending!: Promise<void>;
  act(() => {
    pending = result.current.show();
  });
  await waitFor(() => expect(api.listProcessingJobs).toHaveBeenCalledTimes(1));
  const signal = jest.mocked(api.listProcessingJobs).mock.calls[0][2]!.signal!;
  mockAuth = { ...mockAuth, token: "credential-b" };
  rerender({ id: "3", edit: true });
  await act(async () => {
    resolve({ data: [base], total: 1 });
    await pending;
  });
  expect(signal.aborted).toBe(true);
  expect(result.current.open).toBe(false);
  expect(result.current.history).toBeUndefined();
  rerender({ id: "4", edit: true });
  expect(result.current.job).toBeUndefined();
});
it("requires a fresh read after a known obsolete result and never reports completion", async () => {
  const { result } = setup();
  await details(result);
  jest
    .mocked(api.retryProcessingJob)
    .mockRejectedValueOnce({ kind: "business", status_code: 10997 });
  await act(async () => {
    await result.current.retry();
  });
  expect(result.current.pending).toBe(false);
  expect(result.current.error).toBe(true);
  await act(async () => {
    await result.current.retry();
  });
  expect(api.retryProcessingJob).toHaveBeenCalledTimes(1);
  jest
    .mocked(api.getProcessingJob)
    .mockResolvedValue({ ...base, state: "obsolete", revision: 5, retryable: false });
  await act(async () => {
    await result.current.refresh();
  });
  expect(result.current.job?.state).toBe("obsolete");
  expect(result.current.accepted).toBe(false);
});
it("removes the panel data when a pinned response changes tenant", async () => {
  const { result } = setup();
  await details(result);
  jest.mocked(api.getProcessingJob).mockRejectedValue({ status_code: 19704 });
  await act(async () => {
    await result.current.refresh();
  });
  await waitFor(() => expect(result.current.open).toBe(false));
  expect(result.current.job).toBeUndefined();
  expect(result.current.items).toBeUndefined();
});
