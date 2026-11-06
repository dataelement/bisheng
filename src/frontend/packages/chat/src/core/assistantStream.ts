import { normalizeHostRow, withoutHostSnapshot } from './hostMessages';
import { asRecord, displayText, normalizeFiles, parsePayload, sourceId } from './normalizeHistory';
import type { RawMessage } from './types';
export const assistantRunCategories = ['tool', 'flow', 'knowledge'] as const;
const isRun = (row: RawMessage) => assistantRunCategories.some(category => category === row.category);
const isUser = (row: RawMessage) => row.isSend === true || row.is_bot === false || row.category === 'question';
function runId(row: RawMessage): unknown {
  return asRecord(parsePayload(row.extra)).run_id ?? row.extra;
}
/** Assistant start is a UI placeholder, never a persisted message identity. */
export function startAssistantForHost(rows: readonly unknown[], frame: RawMessage, sessionKey: string): RawMessage[] {
  const raw = rows.map(asRecord);
  const key = `${sessionKey}:assistant:${raw.length}:${String(runId(frame) ?? '')}`;
  return [...raw, normalizeHostRow({ ...frame, chat_id: sessionKey, chat_ui_key: key, chat_source_message_id: undefined,
    id: key, category: isRun(frame) ? frame.category : 'stream_msg',
    is_bot: true, isSend: false, end: false,
    message: isRun(frame) ? parsePayload(frame.message) : '',
    files: [], reasoning_log: '', thought: displayText(frame.intermediate_steps ?? frame.thought) }, { mode: 'assistant', sessionKey })];
}
/** Assistant tokens are deltas; its explicit end_cover frame is the final snapshot. */
export function assistantStreamForHost(rows: readonly unknown[], frame: RawMessage, sessionKey: string, cover = false): RawMessage[] {
  let raw = rows.map(asRecord);
  // The platform error adapter sends this control frame to terminate the turn.
  if (cover && frame.type === 'end_cover' && frame.category === 'tool' && frame.extra === undefined
    && Object.keys(asRecord(parsePayload(frame.message))).length === 0) {
    for (let i = raw.length - 1; i >= 0 && !isUser(raw[i]); i--) {
      if (raw[i].end === false) raw[i] = normalizeHostRow({ ...withoutHostSnapshot(raw[i]), end: true, interrupted: true }, { mode: 'assistant', sessionKey });
    }
    return raw;
  }
  const run = isRun(frame);
  let index = -1;
  for (let i = raw.length - 1; i >= 0; i--) {
    if (isUser(raw[i])) break;
    if (run ? isRun(raw[i]) && runId(raw[i]) === runId(frame) : !isRun(raw[i])) { index = i; break; }
  }
  if (index < 0) {
    raw = startAssistantForHost(raw, frame, sessionKey);
    index = raw.length - 1;
  }
  const replace = cover || frame.type === 'end_cover';
  if (!run && replace && index > 0 && !isUser(raw[index - 1]) && !isRun(raw[index - 1])) {
    raw = raw.filter((_item, i) => i !== index);
    index -= 1;
  }
  const previous = withoutHostSnapshot(raw[index]);
  const payload = parsePayload(frame.message);
  const record = asRecord(payload);
  const text = displayText(record.content ?? payload);
  const reasoning = displayText(record.reasoning_content ?? frame.reasoning_log);
  const final = frame.end === true || ['end', 'end_cover', 'over'].includes(String(frame.type));
  const persistedId = final ? sourceId(frame.message_id ?? frame.messageId) ?? sourceId(previous.chat_source_message_id) : sourceId(previous.chat_source_message_id);
  const issues: string[] = [];
  const files = frame.files === undefined ? previous.files ?? [] : normalizeFiles(frame.files, issues).map(file => ({ ...file.raw, file_name: file.name, file_url: file.url }));
  const thought = displayText(frame.intermediate_steps ?? frame.thought);
  const next: RawMessage = { ...previous, ...frame, chat_id: sessionKey,
    category: run ? frame.category : 'stream_msg',
    chat_ui_key: previous.chat_ui_key, chat_source_message_id: persistedId,
    id: persistedId === undefined ? previous.id : (frame.message_id ?? frame.messageId ?? previous.id ?? persistedId), isSend: false, is_bot: true,
    message: run ? payload : replace ? text : displayText(previous.message) + text,
    reasoning_log: replace && reasoning ? reasoning : displayText(previous.reasoning_log) + reasoning,
    thought: displayText(previous.thought) + (thought ? `${thought}\n` : ''),
    files, end: final, issues };
  if (run && frame.message === undefined) next.message = previous.message;
  raw[index] = normalizeHostRow(next, { mode: 'assistant', sessionKey });
  if (!run && final && !next.message && !next.reasoning_log && !next.thought && Array.isArray(files) && !files.length) {
    raw = raw.filter((_item, i) => i !== index);
  }
  return raw;
}
