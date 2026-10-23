import { historyForHost, sourceId, type ChatMode, type RawMessage } from '@bisheng/chat/core';
import { getChatHistory } from '@/controllers/API';
import { generateUUID } from '@/components/bs-ui/utils';
import { formatDate } from '@/util/utils';
import i18next from 'i18next';
import type { StoreApi } from 'zustand/vanilla';

interface HistoryState {
    chatId: string;
    historyGeneration: number;
    running: boolean;
    historyEnd: boolean;
    messages: unknown[];
    hisMessages: unknown[];
}
export interface HistoryActions {
    loadHistoryMsg: (flowId: string, chatId: string, options: { appendHistory: boolean; lastMsg: string }) => Promise<void>;
    loadMoreHistoryMsg: (flowId: string, appendHistory: boolean) => Promise<void>;
    dispose: () => void;
}
/** HTTP and pagination orchestration are host services, outside Zustand state. */
export function createHistoryAdapter<T extends HistoryState>(store: StoreApi<T>, mode: ChatMode): HistoryActions {
    const update = (state: Partial<HistoryState>) => store.setState(state as Partial<T>);
    const separator = (message: string): RawMessage => ({ category: mode === 'workflow' ? 'separator' : 'divider',
        id: `separator-${generateUUID(8)}`, chat_source_message_id: undefined,
        message, files: [], end: true, create_time: formatDate(new Date(), 'yyyy-MM-ddTHH:mm:ss') });
    return {
        async loadHistoryMsg(flowId, chatId, { appendHistory, lastMsg }) {
            const generation = store.getState().historyGeneration + 1;
            update({ chatId, historyGeneration: generation, historyEnd: false });
            const raw = await getChatHistory(flowId, chatId, 30, 0);
            if (store.getState().historyGeneration !== generation || store.getState().chatId !== chatId) return;
            const rows = historyForHost(raw, { mode, sessionKey: chatId }).reverse();
            if (mode === 'workflow') {
                if (rows.length && lastMsg) rows.push(separator(String(i18next.t('chat.chatEndMessage'))));
                update({ messages: rows.map(row => ({ ...row, his: true })), hisMessages: [] });
            } else {
                if (!appendHistory && rows.length) rows.push(separator(lastMsg));
                update({ messages: appendHistory ? rows : [], hisMessages: appendHistory ? [] : rows });
            }
        },
        async loadMoreHistoryMsg(flowId, appendHistory) {
            const before = store.getState();
            if (before.running || before.historyEnd || !before.chatId) return;
            const previous = before[appendHistory ? 'messages' : 'hisMessages'];
            const first = previous[0] as RawMessage | undefined;
            const cursor = Number(first?.id);
            if (!Number.isInteger(cursor) || cursor <= 0) return;
            const raw = await getChatHistory(flowId, before.chatId, 10, cursor);
            const current = store.getState();
            if (current.historyGeneration !== before.historyGeneration || current.chatId !== before.chatId) return;
            if (raw.some(row => row.chat_id && row.chat_id !== before.chatId)) return;
            const older = historyForHost(raw, { mode, sessionKey: before.chatId, pageKey: String(cursor) }).reverse();
            const seen = new Set<string>();
            const rows = [...older, ...current[appendHistory ? 'messages' : 'hisMessages']].filter(value => {
                const row = value as RawMessage; const id = sourceId(row.id ?? row.message_id);
                if (id === undefined) return true;
                if (seen.has(id)) return false; seen.add(id); return true;
            });
            update({ [appendHistory ? 'messages' : 'hisMessages']: rows, historyEnd: raw.length === 0 });
        },
        dispose() { update({ historyGeneration: store.getState().historyGeneration + 1 }); },
    };
}
