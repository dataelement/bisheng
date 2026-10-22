import { asRecord, normalizeHistory } from './normalizeHistory';
import type { ChatMessage, HistoryOptions, RawMessage } from './types';
const SNAPSHOT = '__bisheng_chat_snapshot';
interface HostSnapshot { message: unknown; files: unknown; id: unknown; messageId: unknown; end: unknown; normalized: ChatMessage }
export function withoutHostSnapshot(value: unknown): RawMessage {
  const raw = { ...asRecord(value) }; delete raw[SNAPSHOT]; return raw;
}
export function withHostSnapshot(row: RawMessage, normalized: ChatMessage): RawMessage {
  const raw = withoutHostSnapshot(row);
  const snapshot: HostSnapshot = { message: raw.message, files: raw.files, id: raw.id, messageId: raw.message_id, end: raw.end, normalized };
  return { ...raw, [SNAPSHOT]: snapshot };
}
export function normalizeHostRow(row: RawMessage, options: HistoryOptions): RawMessage {
  const raw = withoutHostSnapshot(row);
  return withHostSnapshot(raw, normalizeHistory([raw], options)[0]);
}
function readSnapshot(value: unknown): ChatMessage | undefined {
  const row = asRecord(value);
  const cached = asRecord(row[SNAPSHOT]);
  const normalized = asRecord(cached.normalized);
  if (typeof normalized.key !== 'string' || !Array.isArray(normalized.files) || typeof normalized.text !== 'string') return undefined;
  if (row.message !== cached.message || row.files !== cached.files || row.id !== cached.id || row.message_id !== cached.messageId || row.end !== cached.end) return undefined;
  return cached.normalized as ChatMessage;
}
/** Read canonical snapshots without reinterpreting transformed compatibility rows. */
export function messagesForPresentation(rows: readonly unknown[], options: HistoryOptions): ChatMessage[] {
  return rows.map((row, index) => {
    const snapshot = readSnapshot(row);
    if (snapshot) return { ...snapshot, raw: { ...snapshot.raw, ...withoutHostSnapshot(row) } };
    return normalizeHistory([withoutHostSnapshot(row)], { ...options, pageKey: `${options.pageKey ?? 'live'}:${index}` })[0];
  });
}

/** Runtime-only descriptors and UI identities never travel in a host request. */
export function messagesForTransport(rows: readonly unknown[]): RawMessage[] {
  return rows.map(value => {
    const raw = withoutHostSnapshot(value);
    delete raw.chat_ui_key; delete raw.chat_source_message_id;
    return raw;
  });
}
