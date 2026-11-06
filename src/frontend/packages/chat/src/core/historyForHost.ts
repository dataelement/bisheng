import { withHostSnapshot } from './hostMessages';
import { asRecord, normalizeHistory } from './normalizeHistory';
import type { HistoryOptions, RawMessage } from './types';
/** Transitional host-state shape. All message interpretation happens in core. */
export function historyForHost(rows: readonly unknown[], options: HistoryOptions): RawMessage[] {
  return normalizeHistory(rows, options).map(message => {
    const payload = asRecord(message.payload);
    const firstKey = Object.keys(payload)[0];
    const chatKey = 'input' in payload ? 'input' : firstKey === 'data' ? 'query' : firstKey;
    return withHostSnapshot({ ...message.raw, chat_ui_key: message.key, chat_source_message_id: message.sourceMessageId, category: message.kind === 'user' ? 'question' : message.category,
      chatKey, end: message.final, isSend: message.kind === 'user',
      message: message.payload ?? '', thought: message.raw.intermediate_steps,
      reasoning_log: message.reasoning,
      files: message.files.map(file => ({ ...file.raw, file_name: file.name, file_url: file.url })),
      noAccess: true }, message);
  });
}
