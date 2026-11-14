/**
 * What one memory tool call did, read from its redacted event (F132).
 *
 * Memory tool events never carry memory text. The redacted output keeps the
 * operation, the item ids, and — since 2026-11-14 — `ok` and `reason_code`, so a
 * step row can say "remembered 1" or "not remembered: relative time" instead of
 * a bare "memory operation". Events recorded before that have no `ok`; a write
 * without an item id is then read as rejected, which is what an empty id meant.
 */

export type MemoryStepOp = "remember" | "correct" | "forget" | "search";
export type MemoryStepState = "running" | "done" | "failed";

export interface MemoryStep {
  op: MemoryStepOp | null;
  state: MemoryStepState;
  /** Search hits (distinct items); 1 for a successful write. */
  count: number;
  reasonCode: number | null;
  /** Ids of the items a search returned (ids only, never text). */
  itemIds: string[];
}

interface MemoryToolEventLike {
  tool_name?: string | null;
  args?: unknown;
  results?: unknown;
  error?: unknown;
  inflight?: boolean;
}

interface RedactedPayload {
  op?: unknown;
  item_ids?: unknown;
  ok?: unknown;
  reason_code?: unknown;
}

const WRITE_OPS = new Set(["remember", "correct", "forget"]);
/** Rejection codes that have their own wording (common/errcode/memory.py). */
export const MEMORY_REASON_CODES = [12100, 12101, 12102, 12103, 12107, 12110, 12111] as const;

function asPayload(value: unknown): RedactedPayload | null {
  if (typeof value === "string") {
    try {
      return asPayload(JSON.parse(value));
    } catch {
      return null;
    }
  }
  return value && typeof value === "object" ? (value as RedactedPayload) : null;
}

function readOp(...payloads: (RedactedPayload | null)[]): MemoryStepOp | null {
  for (const payload of payloads) {
    const op = typeof payload?.op === "string" ? payload.op : "";
    if (op === "search" || WRITE_OPS.has(op)) return op as MemoryStepOp;
  }
  return null;
}

export function describeMemoryStep(call: MemoryToolEventLike): MemoryStep {
  const args = asPayload(call.args);
  const results = asPayload(call.results);
  const op = readOp(results, args) ?? (call.tool_name === "memory_search" ? "search" : null);
  const itemIds = Array.isArray(results?.item_ids)
    ? [...new Set(results.item_ids.filter((id): id is string => typeof id === "string" && id !== ""))]
    : [];
  const ids = itemIds.length;
  const reasonCode = typeof results?.reason_code === "number" ? results.reason_code : null;

  if (call.inflight) return { op, state: "running", count: 0, reasonCode: null, itemIds: [] };
  if (call.error) return { op, state: "failed", count: 0, reasonCode, itemIds: [] };

  const ok =
    typeof results?.ok === "boolean"
      ? results.ok
      : // Legacy events: a search always answered; a write succeeded only when it returned an id.
        op === "search" || ids > 0;
  if (!ok) return { op, state: "failed", count: 0, reasonCode, itemIds: [] };
  return { op, state: "done", count: op === "search" ? ids : 1, reasonCode: null, itemIds: op === "search" ? itemIds : [] };
}

/**
 * Several searches issued back to back (models often fire them in parallel) read as
 * one step: "found N" counts distinct items across them. Running while any is still
 * running; failed only when none succeeded.
 */
export function mergeMemorySearchSteps(steps: MemoryStep[]): MemoryStep {
  if (steps.length === 1) return steps[0];
  if (steps.some((s) => s.state === "running")) {
    return { op: "search", state: "running", count: 0, reasonCode: null, itemIds: [] };
  }
  const done = steps.filter((s) => s.state === "done");
  if (!done.length) return { ...steps[0], op: "search" };
  const itemIds = [...new Set(done.flatMap((s) => s.itemIds))];
  return { op: "search", state: "done", count: itemIds.length, reasonCode: null, itemIds };
}

type Localize = (key: string, options?: Record<string, unknown>) => string;

/** One-line label for a memory step row, e.g. "没记下：内容里有相对时间". */
export function memoryStepLabel(step: MemoryStep, localize: Localize): string {
  const op = step.op ?? "write";
  if (step.state === "running") return localize(`memory.step.running_${op}`);
  if (step.state === "done") {
    if (op === "search") {
      return step.count > 0
        ? localize("memory.step.done_search", { count: step.count })
        : localize("memory.step.done_search_empty");
    }
    return localize(`memory.step.done_${op}`);
  }
  const known = (MEMORY_REASON_CODES as readonly number[]).includes(step.reasonCode ?? -1);
  const reason = localize(known ? `memory.step.reason_${step.reasonCode}` : "memory.step.reason_other");
  return localize(`memory.step.failed_${op}`, { reason });
}
