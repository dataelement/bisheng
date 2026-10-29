import { useMemo, useRef } from 'react';
import { useRecoilState, useRecoilValue } from 'recoil';
import { useConversationScroll } from '@bisheng/chat';
import { messagesForPresentation } from '@bisheng/chat/core';
import type { ChatMessageType } from '~/@types/chat';
import { getChatHistoryApi } from '~/api/apps';
import { chatApiVersionState, chatIdState, chatsState, currentChatState, currentRunningState } from './store/atoms';
const EMPTY_MESSAGES: ChatMessageType[] = [];

/** Authenticated history requests stay in client; scrolling belongs to chat. */
export function useMessage(shareToken: string) {
    const chatId = useRecoilValue(chatIdState);
    const chatState = useRecoilValue(currentChatState);
    const running = useRecoilValue(currentRunningState)?.running ?? false;
    const apiVersion = useRecoilValue(chatApiVersionState);
    const [, setChats] = useRecoilState(chatsState);
    const messages = chatState?.messages ?? EMPTY_MESSAGES;
    const flow = chatState?.flow;
    const messageScrollRef = useRef<HTMLDivElement>(null);
    const session = `${chatId}:${flow?.id ?? ''}:${apiVersion}:${shareToken}`;
    const scope = useRef({ key: session });
    if (scope.current.key !== session) scope.current = { key: session };
    const normalized = useMemo(() => messagesForPresentation(messages, { mode: flow?.flow_type === 10 ? 'workflow' : 'assistant', sessionKey: chatId }), [chatId, flow?.flow_type, messages]);
    const firstId = messages[0]?.id;
    const canLoadOlder = !!flow && !running && !chatState?.historyEnd && firstId != null && Number.isFinite(Number(firstId));
    const handleLoadOlder = async () => {
        if (!flow || !canLoadOlder) return;
        const origin = scope.current;
        const older = await getChatHistoryApi({ flowId: flow.id, chatId, flowType: String(flow.flow_type), id: Number(firstId), shareToken, apiVersion }) as ChatMessageType[];
        if (scope.current !== origin) return;
        setChats(previous => {
            const chat = previous[chatId];
            if (!chat || scope.current !== origin) return previous;
            const seen = new Set<string>();
            const merged = [...older.reverse(), ...chat.messages].filter(message => {
                if (message.id == null) return true;
                const id = String(message.id); if (seen.has(id)) return false; seen.add(id); return true;
            });
            return { ...previous, [chatId]: { ...chat, messages: merged, historyEnd: older.length === 0 } };
        });
    };
    useConversationScroll({ scrollRef: messageScrollRef, sessionKey: chatId, messages: normalized, canLoadOlder, onLoadOlder: handleLoadOlder });
    return { chatId, messages, messageScrollRef };
}
