/**
 * localStorage-based conversation list for guest (no-login) standalone chat.
 * Messages are stored server-side via v2 WebSocket — only the conversation
 * metadata (id, title, timestamps) lives in localStorage.
 */

const STORAGE_KEY_PREFIX = 'bs_standalone_convos_';

export interface LocalConversation {
  id: string;
  title: string;
  updatedAt: string;
  createdAt: string;
}

function getKey(flowId: string): string {
  return `${STORAGE_KEY_PREFIX}${flowId}`;
}

export function getLocalConversations(flowId: string): LocalConversation[] {
  try {
    const raw = localStorage.getItem(getKey(flowId));
    if (!raw) return [];
    return JSON.parse(raw) as LocalConversation[];
  } catch {
    return [];
  }
}

function saveLocalConversations(flowId: string, convos: LocalConversation[]): void {
  localStorage.setItem(getKey(flowId), JSON.stringify(convos));
}

export function addLocalConversation(flowId: string, conv: LocalConversation): void {
  const list = getLocalConversations(flowId);
  list.unshift(conv);
  saveLocalConversations(flowId, list);
}

export function renameLocalConversation(flowId: string, chatId: string, newTitle: string): void {
  const list = getLocalConversations(flowId);
  const idx = list.findIndex((c) => c.id === chatId);
  if (idx !== -1) {
    list[idx].title = newTitle;
    saveLocalConversations(flowId, list);
  }
}

export function deleteLocalConversation(flowId: string, chatId: string): void {
  const list = getLocalConversations(flowId).filter((c) => c.id !== chatId);
  saveLocalConversations(flowId, list);
}

export function updateLocalConversationTimestamp(flowId: string, chatId: string): void {
  const list = getLocalConversations(flowId);
  const idx = list.findIndex((c) => c.id === chatId);
  if (idx !== -1) {
    list[idx].updatedAt = new Date().toISOString();
    // Move to front (most recent)
    const [item] = list.splice(idx, 1);
    list.unshift(item);
    saveLocalConversations(flowId, list);
  }
}
