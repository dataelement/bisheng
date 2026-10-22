import { asRecord, sourceId } from './normalizeHistory';
import type { ChatMessage } from './types';
export interface RunLabels { used: string; using: string; searched: string; searching: string; offline: string; flowDeleted: string; toolDeleted: string; knowledgeDeleted: string; thinking: string; done: string; interrupted: string }
export interface RunPresentation { title: string; unavailable: boolean }
export function createRunLabels(localize: (key: string) => string): RunLabels {
  return Object.fromEntries(['used', 'using', 'searched', 'searching', 'offline', 'flowDeleted', 'toolDeleted', 'knowledgeDeleted', 'thinking', 'done', 'interrupted']
    .map(key => [key, localize(`shared:app_chat.run.${key}`)])) as unknown as RunLabels;
}
/** Names come from the host's authorized catalog; absent catalogs do not imply deletion. */
export function describeRun(message: ChatMessage, catalogValue: unknown, labels: RunLabels): RunPresentation {
  if (message.raw.interrupted) return { title: labels.interrupted, unavailable: true };
  const catalog = asRecord(catalogValue);
  const field = message.category === 'flow' ? 'flow_list' : message.category === 'knowledge' ? 'knowledge_list' : 'tool_list';
  const entries = Array.isArray(catalog[field]) ? catalog[field].map(asRecord) : [];
  const key = sourceId(asRecord(message.payload).tool_key);
  const selected = message.category === 'knowledge' && key === 'space_retriever' ? entries.filter(item => item.type === 3)
    : entries.filter(item => sourceId(message.category === 'tool' ? item.tool_key : item.id) === key && key !== undefined);
  const name = selected.map(item => typeof item.name === 'string' ? item.name : '').filter(Boolean).join(', ');
  const unavailable = message.category === 'flow' && selected.some(item => item.status === 1);
  if (name) {
    const phase = message.category === 'knowledge' ? (message.final ? labels.searched : labels.searching) : (message.final ? labels.used : labels.using);
    return { title: unavailable ? `${name} ${labels.offline}` : `${phase} ${name}`, unavailable };
  }
  if (entries.length) return { title: message.category === 'flow' ? labels.flowDeleted : message.category === 'knowledge' ? labels.knowledgeDeleted : labels.toolDeleted, unavailable: true };
  return { title: message.final ? labels.done : labels.thinking, unavailable: false };
}
