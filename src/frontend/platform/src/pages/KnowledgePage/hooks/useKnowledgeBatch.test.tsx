import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useKnowledgeBatch } from "./useKnowledgeBatch";
import * as api from "@/controllers/API/knowledgeBatch";
import { BatchOperationDialog } from "../components/BatchOperationDialog";
vi.mock("@/controllers/API/knowledgeBatch");
vi.mock("@/controllers/managementScope", () => ({ managementRequestScope: () => 101 }));
vi.mock("@/controllers/request", () => ({
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
  vi.clearAllMocks();
  vi.mocked(api.inspectBatch).mockResolvedValue({ tenant: "101", inspection: plan });
  vi.mocked(api.precheckBatch).mockResolvedValue(plan);
  vi.mocked(api.confirmBatch).mockResolvedValue(outcome);
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
  vi.mocked(api.precheckBatch).mockResolvedValue({
    ...plan,
    requires_skip_confirmation: true,
    invalid_items: [{ id: 8, type: "file", reason: "no_permission" }],
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
  vi.mocked(api.confirmBatch)
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
  expect(vi.mocked(api.confirmBatch).mock.calls[0]).toEqual(
    vi.mocked(api.confirmBatch).mock.calls[2],
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
  expect(vi.mocked(api.inspectBatch).mock.calls[0][0].items).toHaveLength(1);
  await act(async () => {
    await result.current.confirm(false);
  });
  expect(api.confirmBatch).not.toHaveBeenCalled();
});
it("scope changes retire the complete confirmation and ignore late responses", async () => {
  let done!: (value: Awaited<ReturnType<typeof api.precheckBatch>>) => void;
  vi.mocked(api.precheckBatch).mockReturnValue(
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
it("keeps batch item names, skip reasons, and results in their respective rows", async () => {
  vi.mocked(api.precheckBatch).mockResolvedValue({
    ...plan,
    requires_skip_confirmation: true,
    invalid_items: [{ reason: "no_permission" }],
  });
  function BatchHarness() {
    const operation = useKnowledgeBatch("scope");
    return (
      <>
        <button
          type="button"
          onClick={() => {
            void operation.open({
              ...command,
              items: [...command.items, { id: NaN, type: "file", name: "uploading.txt" }],
            });
          }}
        >
          Start batch
        </button>
        <BatchOperationDialog operation={operation} />
      </>
    );
  }
  render(<BatchHarness />);
  fireEvent.click(screen.getByRole("button", { name: "Start batch" }));
  const available = await screen.findByRole("table", { name: "batch.valid" });
  expect(within(available).getByRole("rowheader", { name: "failed.txt" })).toBeVisible();
  const unavailable = screen.getByRole("table", { name: "batch.invalid" });
  expect(
    within(unavailable).getByRole("row", { name: "batch.unnamed batch.reason_no_permission" }),
  ).toBeVisible();
  expect(
    within(unavailable).getByRole("row", { name: "uploading.txt batch.reason_unsupported" }),
  ).toBeVisible();
  fireEvent.click(screen.getByRole("checkbox", { name: "batch.skip" }));
  fireEvent.click(screen.getByRole("button", { name: "batch.confirm" }));
  const results = await screen.findByRole("table", { name: "batch.results" });
  expect(within(results).getByRole("row", { name: "failed.txt batch.state_accepted" })).toBeVisible();
});

it("shows the space tag permission reason and keeps authorized file names in a blocked batch", async () => {
  const denied = {
    ...plan,
    can_execute: false,
    valid_items: [],
    invalid_items: [{ id: 7, type: "file" as const, name: "editable.txt", reason: "space_tag_permission_required" }],
  };
  vi.mocked(api.inspectBatch).mockResolvedValue({ tenant: "101", inspection: denied });
  vi.mocked(api.precheckBatch).mockResolvedValue(denied);
  function Review() {
    const operation = useKnowledgeBatch("scope");
    return <>
      <button onClick={() => { void operation.open({ ...command, operation: "tag", new_tag_names: ["new"] }); }}>Open</button>
      <BatchOperationDialog operation={operation} />
    </>;
  }
  render(<Review />);
  fireEvent.click(screen.getByRole("button", { name: "Open" }));
  expect(await screen.findByText("editable.txt")).toBeVisible();
  expect(screen.getByText("batch.reason_space_tag_permission_required")).toBeVisible();
  expect(screen.queryByText("batch.unnamed")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "batch.confirm" })).toBeDisabled();
  expect(api.confirmBatch).not.toHaveBeenCalled();
});
