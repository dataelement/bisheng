import { act, renderHook, waitFor } from "@testing-library/react";

import { useKnowledgeBatch } from "./useKnowledgeBatch";
import * as api from "~/api/knowledgeBatch";
jest.mock("~/api/knowledgeBatch", () => ({
  inspectBatch: jest.fn(),
  precheckBatch: jest.fn(),
  confirmBatch: jest.fn(),
}));
jest.mock("~/hooks", () => ({ useAuthContext: () => ({ user: { id: "7", role: "USER" } }) }));
jest.mock("~/api/request", () => ({
  showApiError: (error: Error) => ({
    message: error.message,
    kind: "business",
    presentation: "none",
  }),
}));
const command: api.BatchCommand = {
  spaceId: 3,
  operation: "retry",
  items: [{ id: 7, type: "file", name: "failed.txt" }],
};
const plan = {
  confirmation_id: "plan",
  plan_digest: "digest",
  expires_at: "2030-01-01",
  check_complete: true,
  can_execute: true,
  valid_items: [{ id: 7, type: "file" as const, name: "failed.txt" }],
  invalid_items: [],
  requires_skip_confirmation: false,
  impact: {},
};
const outcome: api.BatchResult = {
  confirmation_id: "plan",
  operation: "retry",
  reused: false,
  items: [{ id: 7, type: "file", state: "accepted" }],
};
beforeEach(() => {
  jest.clearAllMocks();
  jest.mocked(api.inspectBatch).mockResolvedValue({ tenant: "101", inspection: plan });
  jest.mocked(api.precheckBatch).mockResolvedValue(plan);
  jest.mocked(api.confirmBatch).mockResolvedValue(outcome);
});
async function ready(result: { current: ReturnType<typeof useKnowledgeBatch> }) {
  await waitFor(() => expect(result.current.view?.result).toBeDefined());
}
it("cancel does not execute and a prepared plan is not a completed operation", async () => {
  const { result } = renderHook(() => useKnowledgeBatch("scope"));
  let promise!: Promise<api.BatchResult | null>;
  act(() => {
    promise = result.current.open(command);
  });
  await ready(result);
  expect(api.confirmBatch).not.toHaveBeenCalled();
  act(() => result.current.close());
  expect(await promise).toBeNull();
});
it("requires explicit skip and sends only the original three fields", async () => {
  jest.mocked(api.precheckBatch).mockResolvedValue({
    ...plan,
    requires_skip_confirmation: true,
    invalid_items: [{ id: 8, type: "file", reason: "no_permission", error_code: null }],
  });
  const { result } = renderHook(() => useKnowledgeBatch("scope"));
  act(() => {
    void result.current.open(command);
  });
  await ready(result);
  await act(async () => {
    await result.current.confirm(false);
  });
  expect(api.confirmBatch).not.toHaveBeenCalled();
  await act(async () => {
    await result.current.confirm(true);
  });
  expect(api.confirmBatch).toHaveBeenCalledWith(
    command,
    { confirmation_id: "plan", plan_digest: "digest", idempotency_key: "batch:plan" },
    "101",
  );
});
it("lost ACK and pending dispatch keep the same plan and operation", async () => {
  jest
    .mocked(api.confirmBatch)
    .mockRejectedValueOnce(new Error("connection lost"))
    .mockResolvedValueOnce({
      ...outcome,
      items: [{ id: 7, type: "file", state: "pending_dispatch" }],
    })
    .mockResolvedValueOnce(outcome);
  const { result } = renderHook(() => useKnowledgeBatch("scope"));
  let promise!: Promise<api.BatchResult | null>;
  act(() => {
    promise = result.current.open(command);
  });
  await ready(result);
  await act(async () => {
    await result.current.confirm(false);
  });
  act(() => result.current.review());
  expect(api.precheckBatch).toHaveBeenCalledTimes(1);
  await act(async () => {
    await result.current.confirm(false);
  });
  act(() => result.current.close());
  expect(result.current.view).not.toBeNull();
  await act(async () => {
    await result.current.confirm(false);
  });
  expect(jest.mocked(api.confirmBatch).mock.calls[0]).toEqual(
    jest.mocked(api.confirmBatch).mock.calls[2],
  );
  act(() => result.current.close());
  expect((await promise)?.items[0].state).toBe("accepted");
});
it("local uploading placeholders are displayed and require skip without being forged as database IDs", async () => {
  const { result } = renderHook(() => useKnowledgeBatch("scope"));
  act(() => {
    void result.current.open({
      ...command,
      items: [...command.items, { id: NaN, type: "file", name: "uploading.txt" }],
    });
  });
  await ready(result);
  expect(result.current.view?.localInvalid[0].name).toBe("uploading.txt");
  expect(jest.mocked(api.inspectBatch).mock.calls[0][0].items).toHaveLength(1);
  await act(async () => {
    await result.current.confirm(false);
  });
  expect(api.confirmBatch).not.toHaveBeenCalled();
});
it("scope changes retire the complete confirmation and ignore late responses", async () => {
  let done!: (value: Awaited<ReturnType<typeof api.precheckBatch>>) => void;
  jest.mocked(api.precheckBatch).mockReturnValue(
    new Promise((resolve) => {
      done = resolve;
    }),
  );
  const { result, rerender } = renderHook(({ scope }) => useKnowledgeBatch(scope), {
    initialProps: { scope: "old" },
  });
  let promise!: Promise<api.BatchResult | null>;
  act(() => {
    promise = result.current.open(command);
  });
  await waitFor(() => expect(api.precheckBatch).toHaveBeenCalledTimes(1));
  rerender({ scope: "new" });
  expect(await promise).toBeNull();
  await act(async () => {
    done(plan);
  });
  expect(result.current.view).toBeNull();
  expect(api.confirmBatch).not.toHaveBeenCalled();
});
it("accepted result remains visible until acknowledged and is not worker completion", async () => {
  const { result } = renderHook(() => useKnowledgeBatch("scope"));
  act(() => {
    void result.current.open(command);
  });
  await ready(result);
  await act(async () => {
    await result.current.confirm(false);
  });
  expect(result.current.view?.outcome?.items[0].state).toBe("accepted");
  expect(result.current.view).not.toBeNull();
});
