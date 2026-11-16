/**
 * F132 memory signal for app chat (WebSocket).
 *
 * The assistant sends a `memory` message carrying `{turn_id, has_write,
 * has_attribution}`; it is pinned onto the round's answer row as `memory`, which
 * the footer reads back from `message.raw.memory`. Workflow answers never show
 * attribution (spec: a workflow's final output is not attributed).
 */
import { MEMORY_TOOL_NAMES, parseMemorySignal, type MemoryFlags } from "~/api/memory";
import { describeMemoryStep, mergeMemorySearchSteps, type MemoryStep } from "~/components/Memory/memoryStep";

const ASSISTANT_FLOW_TYPE = 5;
const ANSWER_CATEGORIES = new Set(["stream_msg", "answer", "output_msg", "agent_answer"]);

type Row = Record<string, unknown>;

/** Memory UI shows only on a signed-in assistant chat (never guest, share or workflow). */
export function appMemoryEnabled(flowType: unknown, readOnly: boolean, isGuestMode: boolean): boolean {
  return Number(flowType) === ASSISTANT_FLOW_TYPE && !readOnly && !isGuestMode;
}

export function isMemoryFrame(frame: unknown): boolean {
  if (!frame || typeof frame !== "object") return false;
  const { category, type } = frame as Row;
  return category === "memory" || type === "memory";
}

/** Flags and (optional) answer id of a memory frame; null when it is not one. */
export function readMemoryFrame(frame: unknown): { flags: MemoryFlags; messageId?: string } | null {
  if (!isMemoryFrame(frame)) return null;
  const flags = parseMemorySignal(frame);
  if (!flags) return null;
  const raw = frame as Row;
  const id = raw.message_id ?? raw.messageId;
  return { flags, messageId: id != null && id !== "" ? String(id) : undefined };
}

const isUserRow = (row: Row) => row.isSend === true || row.is_bot === false || row.category === "question";
const idsOf = (row: Row) =>
  [row.id, row.message_id, row.chat_source_message_id].filter((v) => v != null).map(String);

/**
 * Pin flags onto the answer they belong to: the row with `messageId` when the
 * frame names one, otherwise the latest answer of the current round. Returns
 * whether a row was found; rows are never mutated in place.
 */
export function attachMemoryFlags<T>(
  rows: T[],
  flags: MemoryFlags,
  messageId?: string,
): { rows: T[]; attached: boolean } {
  let index = -1;
  if (messageId) {
    index = rows.findIndex((row) => idsOf(row as Row).includes(messageId));
  }
  if (index < 0) {
    for (let i = rows.length - 1; i >= 0; i--) {
      const row = rows[i] as Row;
      if (isUserRow(row)) break;
      if (typeof row.category === "string" && ANSWER_CATEGORIES.has(row.category)) {
        index = i;
        break;
      }
    }
  }
  if (index < 0) return { rows, attached: false };
  const next = rows.slice();
  next[index] = { ...(rows[index] as Row), memory: flags } as T;
  return { rows: next, attached: true };
}

/** Signals that arrived before their answer row existed, per chat; flushed when the round ends. */
const pending = new Map<string, MemoryFlags>();

export function queueMemoryFlags(chatId: string, flags: MemoryFlags): void {
  pending.set(chatId, flags);
}

export function takeQueuedMemoryFlags(chatId: string): MemoryFlags | undefined {
  const flags = pending.get(chatId);
  pending.delete(chatId);
  return flags;
}

/**
 * Memory tool runs in assistant chat (AC-09 owner view): the persisted run is
 * already redacted to `{redacted, op, item_ids, ok, reason_code}`. Render a label for
 * what the run did instead of the raw JSON, and keep the default "tool was deleted" title away
 * (memory tools are built in, so they are never in the assistant's tool list).
 */
const RUN_PAYLOAD_FIELDS = ["input_str", "input", "output", "args", "results", "result", "tool_input", "tool_output"];

function parseMaybeJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function asObject(value: unknown): Row {
  const parsed = parseMaybeJson(value);
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Row) : {};
}

function isMemoryRunPayload(payload: unknown): boolean {
  const record = asObject(payload);
  const name = [record.tool_key, record.tool_name, record.name].find((item) => typeof item === "string");
  if (typeof name === "string" && MEMORY_TOOL_NAMES.has(name)) return true;
  if (record.redacted === true) return true;
  return RUN_PAYLOAD_FIELDS.some((field) => asObject(record[field]).redacted === true);
}

interface RunLike {
  kind?: string;
  category?: string;
  payload?: unknown;
  text?: string;
  reasoning?: string;
  raw?: Row;
}

export function isMemoryRun(message: RunLike): boolean {
  return message.kind === "run" && message.category !== "node_run" && isMemoryRunPayload(message.payload);
}

const RUN_INPUT_FIELDS = ["input_str", "input", "args", "tool_input"];
const RUN_OUTPUT_FIELDS = ["output", "results", "result", "tool_output"];

function firstRedacted(record: Row, fields: string[]): Row | undefined {
  for (const field of fields) {
    const value = asObject(record[field]);
    if (value.redacted === true) return value;
  }
  return undefined;
}

/** What a memory run did, read from its redacted input and output (see memoryStep). */
export function memoryRunStep(message: RunLike & { status?: unknown }): MemoryStep {
  const record = asObject(message.payload);
  const name = [record.tool_key, record.tool_name, record.name].find((item) => typeof item === "string");
  const output = firstRedacted(record, RUN_OUTPUT_FIELDS);
  // A failed call is stored as "Error: <redacted json>" (api/v1/callback.py on_tool_error).
  const errored = RUN_OUTPUT_FIELDS.some((field) => typeof record[field] === "string" && /^Error:/.test(record[field] as string));
  return describeMemoryStep({
    tool_name: typeof name === "string" ? name : null,
    args: firstRedacted(record, RUN_INPUT_FIELDS) ?? (record.redacted === true ? record : undefined),
    results: output,
    error: errored || undefined,
    // The start frame carries only the input; the end frame adds the output.
    inflight: !output && !errored && record.redacted !== true,
  });
}

/** Item ids a masked memory search run returned (ids only), for the run's detail list. */
export function memoryRunItemIds(message: { raw?: Row }): string[] {
  const ids = message.raw?.memory_item_ids;
  return Array.isArray(ids) ? ids.filter((id): id is string => typeof id === "string") : [];
}

/**
 * Replace every field a run card could display with a content-free label for that run.
 * Memory searches fired back to back (often in parallel) become one run: the first
 * keeps the merged label and item ids, the rest are dropped, so "found N" does not repeat.
 */
export function maskMemoryRuns<T extends RunLike>(messages: T[], labelFor: (step: MemoryStep) => string): T[] {
  const out: T[] = [];
  let searchRun: { index: number; steps: MemoryStep[] } | null = null;
  const mask = (message: T, step: MemoryStep): T => {
    const label = labelFor(step);
    const toolKey = asObject(message.payload).tool_key;
    return {
      ...message,
      text: label,
      reasoning: "",
      payload: typeof toolKey === "string" ? { tool_key: toolKey, redacted: true } : { redacted: true },
      raw: {
        ...(message.raw ?? {}),
        message: label,
        thought: label,
        intermediate_steps: label,
        // Ids only (never text), and only where a search has items to list.
        ...(step.op === "search" && step.state === "done" && step.itemIds.length ? { memory_item_ids: step.itemIds } : {}),
      },
    };
  };
  for (const message of messages) {
    if (!isMemoryRun(message)) {
      searchRun = null;
      out.push(message);
      continue;
    }
    const step = memoryRunStep(message);
    if (step.op !== "search") {
      searchRun = null;
      out.push(mask(message, step));
      continue;
    }
    if (searchRun) {
      searchRun.steps.push(step);
      out[searchRun.index] = mask(out[searchRun.index], mergeMemorySearchSteps(searchRun.steps));
      continue;
    }
    searchRun = { index: out.length, steps: [step] };
    out.push(mask(message, step));
  }
  return out;
}
