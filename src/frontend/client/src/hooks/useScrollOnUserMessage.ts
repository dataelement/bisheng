import { useEffect, useRef } from 'react';

interface ScrollMessage {
    messageId?: string;
    isCreatedByUser?: boolean;
}

/** Sending reattaches the bottom follow; streaming and older history do not. */
export function useScrollOnUserMessage(
    messages: readonly ScrollMessage[],
    conversationId: string,
    enabled: boolean,
    scrollToBottom: () => void,
) {
    let latestUserMessageId: string | undefined;
    for (let index = messages.length - 1; index >= 0; index--) {
        if (messages[index].isCreatedByUser) {
            latestUserMessageId = messages[index].messageId;
            break;
        }
    }
    const previous = useRef({ conversationId, latestUserMessageId });
    useEffect(() => {
        const last = previous.current;
        previous.current = { conversationId, latestUserMessageId };
        if (enabled && last.conversationId === conversationId && latestUserMessageId
            && last.latestUserMessageId !== latestUserMessageId) {
            scrollToBottom();
        }
    }, [conversationId, enabled, latestUserMessageId, scrollToBottom]);
}
