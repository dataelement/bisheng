import { useRobotDebug } from "@/pages/BuildPage/assistant/robotDebug/useRobotDebug";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ context: vi.fn(), run: vi.fn() }));
vi.mock("@/controllers/API/eplusDebug", () => ({ getRobotDebugContext: mocks.context, runRobotDebug: mocks.run }));
beforeEach(() => {
  mocks.context.mockReset().mockResolvedValue({ assistant_id: "a", test_user_id: 2 });
  mocks.run.mockReset();
});
describe("robot debug history isolation", () => {
  it("clears loading when the pending context request is canceled", async () => {
    let finish: ((value: unknown) => void) | undefined;
    mocks.context.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const { result } = renderHook(() => useRobotDebug("a"));
    expect(result.current.loading).toBe(true);
    act(() => result.current.clear());
    expect(result.current.loading).toBe(false);
    expect(mocks.context.mock.calls[0][2].aborted).toBe(true);
    await act(async () => { finish?.({ assistant_id: "a", test_user_id: 2 }); });
    expect(result.current.context).toBeNull();
    await act(() => result.current.loadContext(3));
    expect(result.current.loading).toBe(false);
    expect(result.current.context?.test_user_id).toBe(2);
  });
  it("stores completed answers only and clears on identity change", async () => {
    mocks.run.mockImplementation(async (_input, onEvent) => {
      onEvent({ type: "answer_delta", data: { text: "answer" } });
      onEvent({ type: "completed", data: { tool_call_count: 0 } });
    });
    const { result } = renderHook(() => useRobotDebug("a"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(() => result.current.send("one"));
    await act(() => result.current.send("two"));
    expect(mocks.run.mock.calls[1][0].history).toEqual([{ question: "one", answer: "answer" }]);
    mocks.context.mockResolvedValue({ assistant_id: "a", test_user_id: 3 });
    await act(() => result.current.loadContext(3));
    await act(() => result.current.send("three"));
    expect(mocks.run.mock.calls[2][0].history).toEqual([]);
    expect(mocks.run.mock.calls[2][0].testUserId).toBe(3);
  });
  it("cancels on clear and ignores late callbacks from the old run", async () => {
    let finish: (() => void) | undefined;
    mocks.run.mockImplementation((_input, onEvent, signal: AbortSignal) => new Promise<void>(resolve => {
      finish = () => { onEvent({ type: "answer_delta", data: { text: "late" } }); resolve(); };
      signal.addEventListener("abort", () => undefined);
    }));
    const { result } = renderHook(() => useRobotDebug("a"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    let pending: Promise<void> | undefined;
    act(() => { pending = result.current.send("one"); });
    act(() => result.current.clear());
    expect(mocks.run.mock.calls[0][2].aborted).toBe(true);
    await act(async () => { finish?.(); await pending; });
    expect(result.current.turns).toEqual([]);
  });
  it("marks failed calls and does not retain their partial answer", async () => {
    mocks.run.mockImplementationOnce(async (_input, onEvent) => {
      onEvent({ type: "answer_delta", data: { text: "partial" } });
      throw new Error("failed");
    }).mockResolvedValue(undefined);
    const { result } = renderHook(() => useRobotDebug("a"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(() => result.current.send("one"));
    expect(result.current.turns[0].state).toBe("failed");
    await act(() => result.current.send("two"));
    expect(mocks.run.mock.calls[1][0].history).toEqual([]);
  });
});
