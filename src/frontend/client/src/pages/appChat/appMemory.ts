/**
 * F132 memory signal for app chat (WebSocket).
 *
 * The assistant sends a `memory` message carrying `{turn_id, has_write,
 * has_attribution}`; it is pinned onto the round's answer row as `memory`, which
 * the footer reads back from `message.raw.memory`. Workflow answers never show
 * attribution (spec: a workflow's final output is not attributed).
 */
import { parseMemorySignal, type MemoryFlags } from "~/api/memory";

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
