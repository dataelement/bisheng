/**
 * Long-term memory API (F132) — every /api/v1/memory endpoint, plus the
 * stream-signal and history-flag helpers the chat surfaces share.
 *
 * Every endpoint acts on the signed-in user only. Calls opt out of the global
 * toast and 403 redirect: the memory surfaces show the backend's reason in
 * place (a rejected add/edit, a failed undo), so a business error rejects with
 * the translated `api_errors.<code>` message instead.
 */
import request from "./request";

interface ApiEnvelope<T> {
  status_code: number;
  status_message?: string;
  data: T;
}

export type MemoryItemType = "fact" | "preference" | "experience";
export type MemoryWriteOp = "remember" | "correct" | "forget";

export interface MemorySource {
  scene: string | null;
  app_id: string | null;
  app_name: string | null;
  chat_id: string | null;
  /** explicit / auto / manual */
  origin: string | null;
}

export interface MemoryItem {
  id: string;
  content: string;
  type: MemoryItemType | string;
  status: string;
  /** "YYYY-MM-DD HH:mm" */
  recorded_at: string | null;
  /** "YYYY-MM-DD" */
  event_time: string | null;
  source: MemorySource;
  /** true = resident memory (carried into every turn) */
  pinned: boolean;
  has_detail: boolean;
}

export interface MemoryItemInput {
  content: string;
  type?: MemoryItemType | string;
  event_time?: string | null;
}

export interface MemoryTurnWrite {
  record_id: number;
  op: MemoryWriteOp | string;
  item_id: string | null;
  related_item_id: string | null;
  undone: boolean;
  item: MemoryItem | null;
  related_item: MemoryItem | null;
}

export interface MemoryTurn {
  turn_id: string | null;
  writes: MemoryTurnWrite[];
  retrieved: MemoryItem[];
  resident: MemoryItem[];
}

/** Stream signal / history flag of one answer. Never carries item text. */
export interface MemoryFlags {
  turn_id: string;
  has_write: boolean;
  has_attribution: boolean;
}

export interface MemorySetting {
  enabled: boolean;
  timezone: string | null;
}

/** Flags of one chat, keyed by the answer's message id. */
export type MemoryFlagsByMessage = Record<string, MemoryFlags>;

const BASE = "/api/v1/memory";

/** Reject business errors with their message; the caller shows it in place. */
const QUIET = { skip403Redirect: true, showError: false };

const dataOf = <T>(response: ApiEnvelope<T>): T => response?.data;

export async function listMemoryItemsApi(): Promise<MemoryItem[]> {
  return (dataOf(await request.get<ApiEnvelope<MemoryItem[]>>(`${BASE}/items`, QUIET)) ?? []) as MemoryItem[];
}

export async function addMemoryItemApi(input: MemoryItemInput): Promise<{ item_id: string }> {
  return dataOf(
    await request.post(
      `${BASE}/items`,
      { content: input.content, type: input.type ?? "fact", event_time: input.event_time ?? null },
      QUIET,
    ),
  );
}

export async function editMemoryItemApi(
  itemId: string,
  input: MemoryItemInput,
): Promise<{ item_id: string; replaced_item_id: string | null }> {
  return dataOf(
    await request.put(
      `${BASE}/items/${encodeURIComponent(itemId)}`,
      { content: input.content, type: input.type ?? "fact", event_time: input.event_time ?? null },
      QUIET,
    ),
  );
}

/** Full text of one of the caller's items; null when the item has none. */
export async function getMemoryItemDetailApi(itemId: string): Promise<string | null> {
  const data = dataOf(
    await request.get<ApiEnvelope<{ detail: string | null }>>(
      `${BASE}/items/${encodeURIComponent(itemId)}/detail`,
      QUIET,
    ),
  );
  return data?.detail ?? null;
}

export async function deleteMemoryItemApi(itemId: string): Promise<void> {
  await request.delete(`${BASE}/items/${encodeURIComponent(itemId)}`, QUIET);
}

export async function clearMemoryItemsApi(): Promise<void> {
  await request.post(`${BASE}/items/clear`, {}, QUIET);
}

export async function undoMemoryWriteApi(
  recordId: number,
): Promise<{ item_id: string | null; related_item_id: string | null }> {
  return dataOf(await request.post(`${BASE}/undo`, { record_id: recordId }, QUIET));
}

export async function getMemorySettingApi(): Promise<MemorySetting> {
  return dataOf(await request.get<ApiEnvelope<MemorySetting>>(`${BASE}/setting`, QUIET));
}

export async function updateMemorySettingApi(enabled: boolean): Promise<MemorySetting> {
  return dataOf(await request.put(`${BASE}/setting`, { enabled }, QUIET));
}

export async function reportMemoryTimezoneApi(timezone: string): Promise<{ changed: boolean }> {
  return dataOf(await request.post(`${BASE}/timezone`, { timezone }, QUIET));
}

/** Notices and attribution of one turn: by `turnId` while live, by `messageId` after a reload. */
export async function getMemoryTurnApi({
  turnId,
  messageId,
}: {
  turnId?: string | null;
  messageId?: string | number | null;
}): Promise<MemoryTurn> {
  const query = turnId
    ? `turn_id=${encodeURIComponent(turnId)}`
    : `message_id=${encodeURIComponent(String(messageId ?? ""))}`;
  const data = dataOf(await request.get<ApiEnvelope<MemoryTurn>>(`${BASE}/turn?${query}`, QUIET));
  return {
    turn_id: data?.turn_id ?? null,
    writes: data?.writes ?? [],
    retrieved: data?.retrieved ?? [],
    resident: data?.resident ?? [],
  };
}

export async function getMemoryFlagsApi(chatId: string): Promise<MemoryFlagsByMessage> {
  return (
    dataOf(
      await request.get<ApiEnvelope<MemoryFlagsByMessage>>(
        `${BASE}/flags?chat_id=${encodeURIComponent(chatId)}`,
        QUIET,
      ),
    ) ?? {}
  );
}

/** Message text of a rejected memory call, falling back to the caller's copy. */
export function memoryErrorMessage(error: unknown, fallback: string): string {
  const message = (error as { message?: unknown })?.message;
  return typeof message === "string" && message.trim() ? message : fallback;
}

/**
 * Read a `memory` stream signal (SSE category or WebSocket message). The
 * payload rides in `message` (object or JSON string); a frame without a turn id
 * is ignored.
 */
export function parseMemorySignal(frame: unknown): MemoryFlags | null {
  if (!frame || typeof frame !== "object") return null;
  const raw = frame as Record<string, unknown>;
  let payload: unknown = raw.message ?? raw.data ?? raw;
  if (typeof payload === "string") {
    try {
      payload = JSON.parse(payload);
    } catch {
      return null;
    }
  }
  if (!payload || typeof payload !== "object") return null;
  const body = payload as Record<string, unknown>;
  const turnId = body.turn_id;
  if (typeof turnId !== "string" || !turnId) return null;
  return { turn_id: turnId, has_write: Boolean(body.has_write), has_attribution: Boolean(body.has_attribution) };
}

/** True when the flags carry anything (the notice shows only for writes). */
export function hasMemoryFlags(flags?: MemoryFlags | null): flags is MemoryFlags {
  return !!flags && (flags.has_write || flags.has_attribution);
}

/**
 * Merge flags fetched by chat id into loaded messages. Untouched messages keep
 * their identity; with nothing to merge the same array comes back.
 */
export function mergeMemoryFlags<T extends { messageId: string; memory?: MemoryFlags }>(
  messages: T[],
  flags: MemoryFlagsByMessage | null | undefined,
): T[] {
  if (!flags || !Object.keys(flags).length) return messages;
  let changed = false;
  const next = messages.map((message) => {
    const found = message.messageId ? flags[message.messageId] : undefined;
    if (!found) return message;
    changed = true;
    return { ...message, memory: found };
  });
  return changed ? next : messages;
}

const isRedactedPayload = (value: unknown): boolean => {
  if (typeof value === "string") {
    try {
      return isRedactedPayload(JSON.parse(value));
    } catch {
      return false;
    }
  }
  return !!value && typeof value === "object" && (value as { redacted?: unknown }).redacted === true;
};

/**
 * A memory tool event as persisted/streamed: tool input and output are each
 * replaced by `{redacted: true, op, item_ids}`. Recognised by name too, so an
 * in-flight call never shows its arguments.
 */
/** The built-in memory tools; other tools that merely start with "memory_" are not memory events. */
export const MEMORY_TOOL_NAMES = new Set(["memory_write", "memory_search"]);

export function isMemoryToolEvent(call: { tool_name?: string | null; args?: unknown; results?: unknown }): boolean {
  if (MEMORY_TOOL_NAMES.has(call.tool_name || "")) return true;
  return isRedactedPayload(call.args) || isRedactedPayload(call.results);
}
