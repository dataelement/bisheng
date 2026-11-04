import { getBareCitationRefs } from '@bisheng/chat/citations';
import type { ChatCitation, ChatMessage } from './chatApi';

/** Old stream-format history omits registries; resolve candidates through the existing permission gate. */
export async function hydrateStreamChatCitations(
  messages: ChatMessage[],
  resolve: (ids: string[]) => Promise<ChatCitation[]>,
): Promise<ChatMessage[]> {
  const idsByMessage = messages.map(message => message.isCreatedByUser ? [] : [...new Set(
    getBareCitationRefs(message.text).map(ref => ref.slice(0, ref.lastIndexOf(':'))),
  )].filter(id => !message.citations?.some(citation => citation.citationId === id)));
  const ids = [...new Set(idsByMessage.flat())];
  if (!ids.length) return messages;
  try {
    const resolved = await resolve(ids);
    return messages.map((message, index) => idsByMessage[index].length ? {
      ...message,
      citations: [...(message.citations || []), ...resolved.filter(citation => idsByMessage[index].includes(citation.citationId))],
    } : message);
  } catch {
    console.warn('[StreamChatHistory] Citation registry lookup failed');
    return messages;
  }
}
