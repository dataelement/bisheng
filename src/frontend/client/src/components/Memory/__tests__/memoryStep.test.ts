import { describeMemoryStep, memoryStepLabel } from "../memoryStep";

// F132: a memory step row says what the call did, never what it wrote.
const localize = (key: string, options?: Record<string, unknown>) =>
  options ? `${key}(${Object.entries(options).map(([k, v]) => `${k}=${v}`).join(",")})` : key;

const call = (results: unknown, extra: Record<string, unknown> = {}) => ({ tool_name: "memory_write", args: { redacted: true, op: "remember", item_ids: [] }, results, ...extra });

describe("memory step", () => {
  it("names a successful write", () => {
    const step = describeMemoryStep(call({ redacted: true, op: "remember", item_ids: ["i-1"], ok: true, reason_code: null }));
    expect(step).toEqual({ op: "remember", state: "done", count: 1, reasonCode: null });
    expect(memoryStepLabel(step, localize)).toBe("memory.step.done_remember");
  });

  it("names a rejected write with its reason", () => {
    const step = describeMemoryStep(call(JSON.stringify({ redacted: true, op: "remember", item_ids: [], ok: false, reason_code: 12102 })));
    expect(step.state).toBe("failed");
    expect(memoryStepLabel(step, localize)).toBe("memory.step.failed_remember(reason=memory.step.reason_12102)");
  });

  it("reads events stored before ok existed: a write without an id was rejected", () => {
    expect(describeMemoryStep(call({ redacted: true, op: "remember", item_ids: [] })).state).toBe("failed");
    expect(describeMemoryStep(call({ redacted: true, op: "remember", item_ids: ["x"] })).state).toBe("done");
    const unknown = describeMemoryStep(call({ redacted: true, op: "remember", item_ids: [], ok: false, reason_code: 99999 }));
    expect(memoryStepLabel(unknown, localize)).toBe("memory.step.failed_remember(reason=memory.step.reason_other)");
  });

  it("counts search hits and says when nothing matched", () => {
    const search = (ids: string[]) => describeMemoryStep({ tool_name: "memory_search", results: { redacted: true, op: "search", item_ids: ids, ok: true } });
    expect(memoryStepLabel(search(["a", "b", "c"]), localize)).toBe("memory.step.done_search(count=3)");
    expect(memoryStepLabel(search([]), localize)).toBe("memory.step.done_search_empty");
  });

  it("shows running and tool errors", () => {
    expect(memoryStepLabel(describeMemoryStep(call(undefined, { inflight: true })), localize)).toBe("memory.step.running_remember");
    expect(describeMemoryStep(call(undefined, { error: "boom" })).state).toBe("failed");
  });
});
