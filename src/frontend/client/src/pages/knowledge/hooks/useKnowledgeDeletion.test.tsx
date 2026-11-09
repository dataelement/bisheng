import { act, renderHook, waitFor } from "@testing-library/react";

import { useKnowledgeDeletion } from "./useKnowledgeDeletion";
import * as api from "~/api/knowledgeDeletion";
jest.mock("~/api/knowledgeDeletion", () => ({
  readDeletionTenant: jest.fn(),
  precheckDeletion: jest.fn(),
  confirmDeletion: jest.fn(),
  getDeletionStatus: jest.fn(),
  inspectReferences: jest.fn(),
  pageReferences: jest.fn(),
}));
jest.mock("~/hooks", () => ({ useAuthContext: () => ({ user: { id: "7", role: "USER" } }) }));
const command = { spaceId: 3, kind: "delete" } as const;
const page = { data: [], page_size: 50, has_more: false, next_cursor: null };
const plan = (digest = "digest", executable = true): api.DeletePrecheck => ({
  confirmation_id: "plan-1",
  plan_digest: digest,
  expires_at: "2030-01-01T00:00:00Z",
  check_complete: true,
  can_execute: executable,
  valid_items: [{ id: 3, type: "space", name: "Space" }],
  invalid_items: [],
  requires_skip_confirmation: false,
  impact: { source_counts: {}, restricted_counts: {}, source_page: page, file_count: 2 },
});
const precheck = jest.mocked(api.precheckDeletion),
  confirm = jest.mocked(api.confirmDeletion),
  status = jest.mocked(api.getDeletionStatus);
beforeEach(() => {
  jest.clearAllMocks();
  jest.mocked(api.readDeletionTenant).mockResolvedValue({
    tenant: "2",
    inspection: {
      check_complete: true,
      blocked: false,
      source_counts: {},
      restricted_counts: {},
      slot_counts: {},
      source_page: page,
    },
  });
  precheck.mockResolvedValue(plan());
  confirm.mockResolvedValue({ job_id: "plan-1", state: "succeeded" });
});
async function ready(result: { current: ReturnType<typeof useKnowledgeDeletion> }) {
  await waitFor(() => expect(result.current.view?.result).toBeDefined());
}
it("keeps the immutable three-field plan through a lost ACK and completes only on succeeded", async () => {
  confirm
    .mockRejectedValueOnce(new Error("connection lost"))
    .mockResolvedValueOnce({ job_id: "plan-1", state: "running" });
  status.mockResolvedValue({ job_id: "plan-1", state: "succeeded" });
  const { result } = renderHook(() => useKnowledgeDeletion("scope"));
  let done!: Promise<boolean>;
  act(() => {
    done = result.current.open(command);
  });
  await ready(result);
  await act(async () => {
    await result.current.confirm(false, false);
  });
  expect(result.current.view?.dispatched).toBe(true);
  expect(precheck).toHaveBeenCalledTimes(1);
  await act(async () => {
    await result.current.confirm(false, false);
  });
  expect(confirm.mock.calls[0]).toEqual(confirm.mock.calls[1]);
  expect(confirm.mock.calls[0][1]).toEqual({
    confirmation_id: "plan-1",
    plan_digest: "digest",
    idempotency_key: "delete:plan-1",
  });
  expect(result.current.view?.status?.state).toBe("running");
  act(() => result.current.refresh());
  expect(precheck).toHaveBeenCalledTimes(1);
  await act(async () => {
    await result.current.status();
  });
  expect(await done).toBe(true);
  expect(result.current.view).toBeNull();
});
it("cancels before dispatch without deleting", async () => {
  const { result } = renderHook(() => useKnowledgeDeletion("scope"));
  let done!: Promise<boolean>;
  act(() => {
    done = result.current.open(command);
  });
  await ready(result);
  act(() => result.current.cancel());
  expect(await done).toBe(false);
  expect(confirm).not.toHaveBeenCalled();
});
it("requires the exact partial selection acknowledgement", async () => {
  precheck.mockResolvedValue({
    ...plan(),
    requires_skip_confirmation: true,
    invalid_items: [{ reason: "referenced", error_code: null }],
  });
  const { result } = renderHook(() => useKnowledgeDeletion("scope"));
  act(() => {
    void result.current.open({ spaceId: 3, kind: "files", items: [{ id: 5, type: "folder" }] });
  });
  await ready(result);
  await act(async () => {
    await result.current.confirm(false, false);
  });
  expect(confirm).not.toHaveBeenCalled();
  await act(async () => {
    await result.current.confirm(true, false);
  });
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(Object.keys(confirm.mock.calls[0][1]).sort()).toEqual([
    "confirmation_id",
    "idempotency_key",
    "plan_digest",
  ]);
});
it("rechecks force as a new signed plan and requires danger acknowledgement", async () => {
  precheck.mockResolvedValueOnce(plan("ordinary", false)).mockResolvedValueOnce(plan("force"));
  const { result } = renderHook(() => useKnowledgeDeletion("scope"));
  act(() => {
    void result.current.open(command);
  });
  await ready(result);
  await act(async () => {
    result.current.force();
  });
  await waitFor(() => expect(result.current.view?.result?.plan_digest).toBe("force"));
  expect(precheck.mock.calls[1]).toEqual([command, true, "2"]);
  await act(async () => {
    await result.current.confirm(false, false);
  });
  expect(confirm).not.toHaveBeenCalled();
  await act(async () => {
    await result.current.confirm(false, true);
  });
  expect(confirm.mock.calls[0][1].plan_digest).toBe("force");
});
it("has no force path for files or clear", async () => {
  const { result } = renderHook(() => useKnowledgeDeletion("scope"));
  act(() => {
    void result.current.open({ spaceId: 3, kind: "clear" });
  });
  await ready(result);
  act(() => result.current.force());
  expect(precheck).toHaveBeenCalledTimes(1);
});
it("rejects incomplete checking without creating a confirmation", async () => {
  precheck.mockResolvedValue({ ...plan(), check_complete: false });
  const { result } = renderHook(() => useKnowledgeDeletion("scope"));
  act(() => {
    void result.current.open(command);
  });
  await ready(result);
  await act(async () => {
    await result.current.confirm(true, true);
    result.current.force();
  });
  expect(confirm).not.toHaveBeenCalled();
  expect(precheck).toHaveBeenCalledTimes(1);
});
it("retires permission or scope changes even while precheck is pending", async () => {
  let resolve!: (value: api.DeletePrecheck) => void;
  precheck.mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  const { result, rerender } = renderHook(({ scope }) => useKnowledgeDeletion(scope), {
    initialProps: { scope: "a" },
  });
  let done!: Promise<boolean>;
  act(() => {
    done = result.current.open(command);
  });
  rerender({ scope: "b" });
  expect(await done).toBe(false);
  await act(async () => {
    resolve(plan());
  });
  expect(result.current.view).toBeNull();
  expect(confirm).not.toHaveBeenCalled();
});
it("pages references without issuing a deletion plan", async () => {
  jest.mocked(api.readDeletionTenant).mockResolvedValue({
    tenant: "2",
    inspection: {
      check_complete: true,
      blocked: true,
      source_counts: {},
      restricted_counts: { assistant: 2 },
      slot_counts: { assistant: 3 },
      source_page: { ...page, has_more: true, next_cursor: "cursor" },
    },
  });
  jest.mocked(api.pageReferences).mockResolvedValue(page);
  const { result } = renderHook(() => useKnowledgeDeletion("scope"));
  act(() => {
    void result.current.open(command, true);
  });
  await waitFor(() => expect(result.current.view?.inspection).toBeDefined());
  await act(async () => {
    await result.current.more();
  });
  expect(api.pageReferences).toHaveBeenCalledWith(command, "cursor", "2");
  expect(precheck).not.toHaveBeenCalled();
  expect(confirm).not.toHaveBeenCalled();
});
