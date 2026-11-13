import { isMemoryToolEvent } from "~/api/memory";
import { isMemoryRun, maskMemoryRuns } from "../appMemory";

// F132 AC-09 (owner view): memory tool runs render a placeholder, never raw JSON.
const PLACEHOLDER = "memory-operation";
describe("memory runs in assistant chat", () => {
  const redacted = JSON.stringify({ redacted: true, op: "remember", item_ids: ["i-1"] });

  it("masks a built-in memory tool run", () => {
    const run = { kind: "run", category: "tool", payload: { tool_key: "memory_write", input: redacted }, text: redacted, raw: {} };
    const [masked] = maskMemoryRuns([run], PLACEHOLDER);
    expect(isMemoryRun(run)).toBe(true);
    expect(masked.text).toBe(PLACEHOLDER);
    expect(JSON.stringify(masked)).not.toContain("item_ids");
  });

  it("leaves other tools, including third-party memory_* tools, untouched", () => {
    const other = { kind: "run", category: "tool", payload: { tool_key: "memory_store", input: '{"k":"v"}' }, text: "x", raw: {} };
    expect(isMemoryRun(other)).toBe(false);
    expect(maskMemoryRuns([other], PLACEHOLDER)[0]).toBe(other);
  });

  it("recognises memory tool events by exact name or redacted payload", () => {
    expect(isMemoryToolEvent({ tool_name: "memory_search" })).toBe(true);
    expect(isMemoryToolEvent({ tool_name: "memory_store", args: { k: 1 } })).toBe(false);
    expect(isMemoryToolEvent({ tool_name: "anything", results: redacted })).toBe(true);
  });
});
