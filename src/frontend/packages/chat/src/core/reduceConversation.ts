import { messageKind, normalizeFiles } from './normalizeHistory';
import type { ChatMessage, ConversationEvent, ConversationSnapshot } from './types';
export function createConversation(sessionKey: string): ConversationSnapshot {
  return { sessionKey, messages: [], running: false, error: null };
}
export function reduceConversation(state: ConversationSnapshot, event: ConversationEvent): ConversationSnapshot {
  if (event.sessionKey !== state.sessionKey) return state;
  if (event.type === 'clear') return createConversation(state.sessionKey);
  if (event.type === 'running') return { ...state, running: event.running };
  if (event.type === 'error') return { ...state, running: false, error: event.error };
  if (event.type === 'history') {
    const entries = event.prepend ? [...event.messages, ...state.messages] : [...state.messages, ...event.messages];
    const seen = new Set<string>();
    return { ...state, messages: entries.filter(message => { const identity = message.sourceMessageId === undefined ? message.key : `server:${message.sourceMessageId}`;
      if (seen.has(identity)) return false; seen.add(identity); return true; }) };
  }
  const index = state.messages.findIndex(item => item.key === event.key
    || (event.sourceMessageId !== undefined && item.sourceMessageId === event.sourceMessageId));
  const previous = state.messages[index];
  const issues = [...previous?.issues ?? []];
  const message: ChatMessage = { key: previous?.key ?? event.key,
    sourceMessageId: event.sourceMessageId ?? previous?.sourceMessageId,
    parentMessageId: previous?.parentMessageId, turnId: previous?.turnId,
    kind: messageKind(event.category), category: event.category,
    text: event.operation === 'append' ? (previous?.text ?? '') + event.text : event.text,
    reasoning: event.operation === 'append' ? (previous?.reasoning ?? '') + (event.reasoning ?? '') : event.reasoning ?? previous?.reasoning ?? '',
    final: event.final, payload: event.raw?.message ?? previous?.payload ?? event.text,
    raw: { ...previous?.raw, ...event.raw },
    files: event.raw?.files === undefined ? previous?.files ?? [] : normalizeFiles(event.raw.files, issues), issues };
  return { ...state, messages: index < 0 ? [...state.messages, message] : state.messages.map((item, i) => i === index ? message : item) };
}
