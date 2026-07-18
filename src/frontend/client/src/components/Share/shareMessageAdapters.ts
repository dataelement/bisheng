import type { ChatMessage } from '~/api/chatApi';
import type { TMessage } from '~/types/chat';

type SharedMessageInput = TMessage & Partial<ChatMessage>;

function toStringValue(value: unknown, fallback = '') {
  return typeof value === 'string' ? value : fallback;
}

export function toSharedChatMessages(messages: TMessage[] = []): ChatMessage[] {
  return messages.map((rawMessage, index) => {
    const message = rawMessage as SharedMessageInput;
    const messageId = toStringValue(message.messageId, `shared-${index}`);
    const parentMessageId = toStringValue(message.parentMessageId);
    const conversationId = toStringValue(message.conversationId);
    const text = toStringValue(message.text);
    const isCreatedByUser = typeof message.isCreatedByUser === 'boolean'
      ? message.isCreatedByUser
      : false;

    return {
      ...message,
      messageId,
      parentMessageId,
      conversationId,
      text,
      isCreatedByUser,
      sender: toStringValue(message.sender, isCreatedByUser ? 'user' : 'assistant'),
      createdAt: toStringValue(message.createdAt),
      citations: message.citations ?? null,
      files: message.files ?? [],
    };
  });
}
