import type { ChatAttachment, ChatMessage, HistoryOptions, MessageKind, RawMessage } from './types';
export function asRecord(value: unknown): RawMessage {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as RawMessage : {};
}
export function sourceId(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() !== '' ? value : typeof value === 'number' && Number.isFinite(value) ? String(value) : undefined;
}
export function parsePayload(value: unknown): unknown {
  if (typeof value !== 'string' || !/^\s*[[{]/.test(value)) return value;
  try { return JSON.parse(value) as unknown; } catch { return value; }
}
export function messageKind(category: string, user = false): MessageKind {
  if (['tool_call', 'tool_result'].includes(category)) return 'hidden';
  if (['reasoning', 'reasoning_answer'].includes(category)) return 'reasoning';
  if (['system', 'guide', 'guide_word', 'guide_question', 'divider', 'separator'].includes(category)) return 'system';
  if (user || ['question', 'input'].includes(category)) return 'user';
  if (['answer', 'agent_answer', 'output_msg', 'stream_msg'].includes(category)) return 'answer';
  if (['node_run', 'tool', 'flow', 'knowledge', 'processing'].includes(category)) return 'run';
  if (category === 'output_with_input_msg') return 'form';
  if (category === 'output_with_choose_msg') return 'choice';
  if (['system', 'guide_word', 'guide_question', 'divider'].includes(category)) return 'system';
  if (['report', 'file'].includes(category)) return 'file';
  return 'unknown';
}
export function displayText(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return '';
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.map(displayText).filter(Boolean).join('\n');
  const record = asRecord(value);
  for (const key of ['msg', 'content', 'input', 'query', 'text', 'guide_word', 'status_message']) {
    if (record[key] !== undefined && record[key] !== null) return displayText(record[key]);
  }
  return Object.entries(record).filter(([key]) => !['reasoning_content', 'data'].includes(key))
    .map(([key, item]) => `${key}: ${displayText(item)}`).join('\n');
}
export function normalizeFiles(value: unknown, issues: string[]): ChatAttachment[] {
  const parsed = parsePayload(value);
  if (parsed === null || parsed === undefined || parsed === '') return [];
  if (!Array.isArray(parsed)) { issues.push('invalid-files'); return []; }
  return parsed.map(item => {
    const raw = asRecord(item);
    return { id: sourceId(raw.file_id ?? raw.id), name: String(raw.file_name ?? raw.name ?? ''),
      url: String(raw.file_url ?? raw.filepath ?? raw.file_path ?? raw.path ?? raw.url ?? ''), raw };
  });
}
export function normalizeHistory(rows: readonly unknown[], options: HistoryOptions): ChatMessage[] {
  return rows.map((row, index) => {
    const raw = asRecord(row);
    const payload = parsePayload(raw.message);
    const record = asRecord(payload);
    const issues: string[] = [];
    const id = 'chat_source_message_id' in raw ? sourceId(raw.chat_source_message_id) : raw.end === false ? undefined : sourceId(raw.message_id ?? raw.id);
    const category = typeof raw.category === 'string' ? raw.category : 'unknown';
    const user = typeof raw.isSend === 'boolean' ? raw.isSend : raw.is_bot === true || raw.is_bot === 1 ? false : raw.is_bot === false || raw.is_bot === 0 ? true : category === 'question';
    const files = normalizeFiles(raw.files, issues);
    const kind = category === 'input' && 'input_schema' in record ? 'hidden' : messageKind(category, user);
    let text = displayText(payload);
    if (!text && ['system', 'guide'].includes(category)) text = displayText(raw.thought ?? raw.intermediate_steps);
    if (kind === 'user' && files.length) {
      const names = new Set(files.map(file => file.name));
      const lines = text.split('\n');
      while (lines.length && names.has(lines[0])) lines.shift();
      text = lines.join('\n');
    }
    return { key: sourceId(raw.chat_ui_key) ?? (id !== undefined ? `${options.sessionKey}:server:${id}` : `${options.sessionKey}:history:${options.pageKey ?? 'first'}:${index}`),
      sourceMessageId: id, parentMessageId: sourceId(raw.parent_message_id ?? raw.parentMessageId), turnId: sourceId(raw.turn_id),
      kind, category, text,
      reasoning: displayText(record.reasoning_content ?? raw.reasoning_log ?? raw.intermediate_steps),
      payload, files, final: raw.end !== false, raw, issues };
  });
}
