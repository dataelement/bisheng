import { isMemoryToolEvent } from "~/api/memory";
import { isMemoryRun, maskMemoryRuns, memoryRunItemIds, memoryRunStep } from "../appMemory";

// F132 AC-09 (owner view): memory tool runs render a placeholder, never raw JSON.
const PLACEHOLDER = "memory-operation";
describe("memory runs in assistant chat", () => {
  const redacted = JSON.stringify({ redacted: true, op: "remember", item_ids: ["i-1"] });

  it("masks a built-in memory tool run", () => {
    const run = { kind: "run", category: "tool", payload: { tool_key: "memory_write", input: redacted }, text: redacted, raw: {} };
    const [masked] = maskMemoryRuns([run], () => PLACEHOLDER);
    expect(isMemoryRun(run)).toBe(true);
    expect(masked.text).toBe(PLACEHOLDER);
    expect(JSON.stringify(masked)).not.toContain("item_ids");
  });

  it("leaves other tools, including third-party memory_* tools, untouched", () => {
    const other = { kind: "run", category: "tool", payload: { tool_key: "memory_store", input: '{"k":"v"}' }, text: "x", raw: {} };
    expect(isMemoryRun(other)).toBe(false);
    expect(maskMemoryRuns([other], () => PLACEHOLDER)[0]).toBe(other);
  });

  it("merges back-to-back searches into one run that lists their distinct items", () => {
    const search = (ids: string[]) => ({
      kind: "run",
      category: "tool",
      payload: { tool_key: "memory_search", output: JSON.stringify({ redacted: true, op: "search", item_ids: ids, ok: true }) },
      text: "",
      raw: {},
    });
    const answer = { kind: "answer", category: "answer", payload: {}, text: "done", raw: {} };
    const out = maskMemoryRuns([search(["a", "b"]), search(["b", "c"]), answer, search(["d"])], (step) => `found ${step.count}`);
    expect(out.map((m) => m.text)).toEqual(["found 3", "done", "found 1"]);
    expect(memoryRunItemIds(out[0])).toEqual(["a", "b", "c"]);
    expect(memoryRunItemIds(out[2])).toEqual(["d"]);
  });

  it("recognises memory tool events by exact name or redacted payload", () => {
    expect(isMemoryToolEvent({ tool_name: "memory_search" })).toBe(true);
    expect(isMemoryToolEvent({ tool_name: "memory_store", args: { k: 1 } })).toBe(false);
    expect(isMemoryToolEvent({ tool_name: "anything", results: redacted })).toBe(true);
  });

  it("reads what each run did from its redacted output", () => {
    const run = (output: unknown) => ({ kind: "run", category: "tool", payload: { tool_key: "memory_write", input_str: redacted, output }, raw: {} });
    expect(memoryRunStep(run(JSON.stringify({ redacted: true, op: "remember", item_ids: ["i-1"], ok: true })))).toMatchObject({ op: "remember", state: "done" });
    expect(memoryRunStep(run(JSON.stringify({ redacted: true, op: "remember", item_ids: [], ok: false, reason_code: 12102 })))).toMatchObject({ state: "failed", reasonCode: 12102 });
    expect(memoryRunStep(run('Error: {"redacted": true, "op": "remember", "item_ids": []}'))).toMatchObject({ state: "failed" });
    expect(memoryRunStep({ kind: "run", category: "tool", payload: { tool_key: "memory_search", input_str: redacted }, raw: {} })).toMatchObject({ state: "running" });
  });
});
