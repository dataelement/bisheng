// @ts-strict-ignore
import { startAssistantForHost, assistantStreamForHost } from '@bisheng/chat/core';
import { ChatMessageType } from '@/types/chat';
import { formatDate } from '@/util/utils';
import { createStore } from 'zustand/vanilla';
import { createHistoryAdapter } from '@/components/bs-comp/appChat/historyAdapter';
import { createMessageStoreScope } from '@/components/bs-comp/appChat/createMessageStoreScope';

/**
 * 会话消息管理
 */

type State = {
    eventTarget: EventTarget,
    historyGeneration: number,
    running: boolean,
    inputLocked: boolean,
    /**
     * 会话 ID
     * 变更会触发 ws建立，解锁滚动
     */
    chatId: string,
    /** 没有更多历史纪录 */
    historyEnd: boolean,
    messages: ChatMessageType[]
    /** 历史回话独立存储 */
    hisMessages: ChatMessageType[]
    /**
     * 控制引导问题的显示状态
     */
    showGuideQuestion: boolean
}

type Actions = {
    setInputLocked: (locked: boolean) => void;
    destory: () => void;
    createSendMsg: (inputs: any, inputKey?: string) => void;
    createWsMsg: (data: any) => void;
    updateCurrentMessage: (wsdata: any, cover: boolean) => void;
    changeChatId: (chatId: string) => void;
    startNewRound: (str: string) => void;
    insetSeparator: (text: string) => void;
    insetSystemMsg: (text: string) => void;
    insetBsMsg: (text: string) => void;
    setShowGuideQuestion: (text: boolean) => void;
    closeDanglingRunLogs: () => void;
    clearMsgs: () => void;
}



const runLogsTypes = ['tool', 'flow', 'knowledge']

export const createMessageStore = () => {
const store = createStore<State & Actions>((set, get) => ({
    eventTarget: new EventTarget(),
    historyGeneration: 0,
    running: false,
    inputLocked: false,
    chatId: '',
    messages: [],
    hisMessages: [],
    historyEnd: false,
    showGuideQuestion: false,
    setShowGuideQuestion(bln: boolean) {
        set({ showGuideQuestion: bln })
    },
    /**
     * A tool card only closes when its `end` frame arrives. Lose one — a
     * serialization failure, a dropped socket — and the card spins forever, with
     * nothing to recover it: the round is over and nothing was persisted. So on
     * session close, settle whatever is still open and mark it interrupted
     * rather than leaving a success tick it never earned.
     */
    closeDanglingRunLogs() {
        const messages = get().messages
        if (!messages.some(msg => runLogsTypes.includes(msg.category) && !msg.end)) return
        set({
            messages: messages.map(msg =>
                runLogsTypes.includes(msg.category) && !msg.end
                    ? { ...msg, end: true, interrupted: true }
                    : msg
            )
        })
    },
    clearMsgs() {
        set({ historyGeneration: get().historyGeneration + 1, hisMessages: [], messages: [], historyEnd: true });
    },
    destory() {
        set({
            historyGeneration: get().historyGeneration + 1, chatId: '', messages: [] })
    },
    createSendMsg(inputs, inputKey) {
        console.log('change createSendMsg', inputs, inputKey);

        set((state) => ({
            messages:
                [...state.messages, {
                    isSend: true,
                    message: inputs,
                    chatKey: inputKey,
                    thought: '',
                    category: '',
                    files: [],
                    end: false,
                    user_name: "",
                    create_time: formatDate(new Date(), 'yyyy-MM-ddTHH:mm:ss')
                }]
        }))
    },
    // start
    createWsMsg(data) {
        set({ messages: startAssistantForHost(get().messages, data, get().chatId) as unknown as ChatMessageType[] });
    },
    updateCurrentMessage(data, cover = false) {
        set({ messages: assistantStreamForHost(get().messages, data, get().chatId, cover) as unknown as ChatMessageType[] });
    },
    setInputLocked(inputLocked) { set({ inputLocked }); },
    changeChatId(chatId) {
        set((state) => ({ chatId }))
    },
    startNewRound(str) {
        get().insetSeparator(str)
        set((state) => ({ showGuideQuestion: true }))
    },
    insetSeparator(text) {
        set((state) => ({
            messages: [...state.messages, {
                ...bsMsgItem,
                id: Math.random() * 1000000,
                category: 'divider',
                message: text,
            }]
        }))
    },
    insetSystemMsg(text) {
        set((state) => ({
            messages: [...state.messages, {
                ...bsMsgItem,
                id: Math.random() * 1000000,
                category: 'guide',
                thought: text,
            }]
        }))
    },
    insetBsMsg(text) {
        set((state) => ({
            messages: [...state.messages, {
                ...bsMsgItem,
                id: 0,
                category: 'guide',
                thought: '',
                message: text
            }]
        }))
    }
}));
return Object.assign(store, { services: createHistoryAdapter(store, 'assistant') });
};
export const { MessageStoreProvider, useMessageStore } = createMessageStoreScope(createMessageStore);


const bsMsgItem = {
    id: Math.random() * 1000000,
    isSend: false,
    message: '',
    chatKey: '',
    thought: '',
    category: '',
    files: [],
    end: true,
    user_name: ''
}
