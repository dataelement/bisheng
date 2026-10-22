import { withHostSnapshot, messagesForPresentation } from './hostMessages';
import { asRecord, displayText, sourceId } from './normalizeHistory';
import { createConversation, reduceConversation } from './reduceConversation';
import type { ChatMessage, RawMessage } from './types';

/** Workflow StreamMsgData carries deltas; StreamMsgOverData carries the snapshot. */
export function applyWorkflowStream(messages: readonly ChatMessage[], frame: RawMessage, sessionKey: string): ChatMessage[] {
  const payload = asRecord(frame.message);
  const uniqueId = sourceId(payload.unique_id);
  const outputKey = sourceId(payload.output_key) ?? '';
  const streamKey = uniqueId === undefined ? undefined : `${sessionKey}:stream:${uniqueId}:${outputKey}`;
  const persistedId = sourceId(frame.message_id);
  const previous = messages.find(message => message.key === streamKey
    || (persistedId !== undefined && message.sourceMessageId === persistedId));
  const key = previous?.key ?? streamKey ?? (persistedId === undefined ? undefined : `${sessionKey}:server:${persistedId}`);
  // Invalid frames have no safe identity to merge into; the host may report them.
  if (key === undefined) return [...messages];
  const final = frame.type === 'end' || frame.type === 'over';
  const next = reduceConversation({ ...createConversation(sessionKey), messages: [...messages] }, {
    type: 'message', sessionKey, key, sourceMessageId: final ? persistedId : undefined,
    category: String(frame.category ?? 'stream_msg'), text: displayText(payload.msg),
    reasoning: payload.reasoning_content === undefined ? undefined : displayText(payload.reasoning_content),
    operation: final ? 'replace' : 'append', final, raw: frame,
  });
  return next.messages;
}

/** Bind the pure interpretation to an existing application's message shape. */
export function workflowStreamForHost(rows: readonly unknown[], frame: RawMessage, sessionKey: string): RawMessage[] {
  const messages = messagesForPresentation(rows, { mode: 'workflow', sessionKey });
  return applyWorkflowStream(messages, frame, sessionKey).map(message => messages.includes(message) ? asRecord(rows[messages.indexOf(message)]) : withHostSnapshot({
    ...message.raw, chat_ui_key: message.key, chat_source_message_id: message.sourceMessageId, id: message.sourceMessageId === undefined ? message.key : (message.raw.message_id ?? message.raw.id ?? message.sourceMessageId),
    message_id: message.sourceMessageId === undefined ? message.key : (message.raw.message_id ?? message.raw.id ?? message.sourceMessageId), message: message.text,
    reasoning_log: message.reasoning, end: message.final,
    files: message.files.map(file => ({ ...file.raw, file_name: file.name, file_url: file.url })),
  }, message));
}
