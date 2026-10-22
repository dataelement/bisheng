// @ts-strict-ignore
import { workflowStreamForHost } from '@bisheng/chat/core';
import { generateUUID } from '@/components/bs-ui/utils';
import { WorkflowMessage } from '@/types/flow';
import { formatDate } from '@/util/utils';
import cloneDeep from 'lodash-es/cloneDeep';
import { createStore } from 'zustand/vanilla';
import { createHistoryAdapter } from '@/components/bs-comp/appChat/historyAdapter';
import { createMessageStoreScope } from '@/components/bs-comp/appChat/createMessageStoreScope';
import { normalizeCitationItems } from '@/components/bs-comp/chatComponent/citationUtils';

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
    messages: WorkflowMessage[]
    /** 历史回话独立存储 */
    hisMessages: any[]
    /**
     * 控制引导问题的显示状态
     */
    showGuideQuestion: boolean
    questions: string[];
    inputForm: null | any
}

type Actions = {
    setQuestions: (questions: string[]) => void;
    setInputLocked: (locked: boolean) => void;
    destory: () => void;
    createSendMsg: (msg: string) => void;
    createWsMsg: (data: any) => void;
    streamWsMsg: (data: any) => void;
    changeChatId: (chatId: string) => void;
    startNewRound: (str: string) => void;
    insetSeparator: (text: string) => void;
    insetSystemMsg: (text: string) => void;
    insetBsMsg: (text: string) => void;
    setShowGuideQuestion: (text: boolean) => void;
    clearMsgs: () => void;
    setInputForm: (inputForm: any) => void;
}




export const createMessageStore = () => {
const store = createStore<State & Actions>((set, get) => ({
    eventTarget: new EventTarget(),
    historyGeneration: 0,
    chatId: '',
    messages: [],
    inputForm: null,
    running: false,
    inputLocked: true,
    hisMessages: [],
    historyEnd: false,
    questions: [],
    showGuideQuestion: false,
    setQuestions(questions) { set({ questions: questions.filter(question => typeof question === "string" && question.trim()) }); },
    setInputLocked(inputLocked) { set({ inputLocked }); },
    changeChatId(chatId) {
        set((state) => ({ chatId }))
    },
    // start
    createWsMsg(data) {
        console.log('change createWsMsg');
        set((state) => {
            let newChat = cloneDeep(state.messages);
            const { category, flow_id, chat_id, message_id, files, is_bot, extra, liked, message, receiver, type, source, user_id, reasoning_log } = data
            // 删除与历史消息中message_id相同的消息,则删除
            const messageId = message_id || (category === "guide_word" ? generateUUID(4) : '') // 后端没给,临时生成一个
            newChat = newChat.filter((item => !(item.message_id === message_id && item.his)))
            newChat.push({
                category, flow_id, chat_id,
                message_id: messageId,
                files, is_bot,
                message, receiver, source, user_id,
                liked: !!liked,
                end: type === 'over',
                sender: '',
                node_id: message?.node_id || '',
                create_time: formatDate(new Date(), 'yyyy-MM-ddTHH:mm:ss'),
                extra,
                reasoning_log,
                citations: normalizeCitationItems(data)
            })
            return { messages: newChat }
        })
    },
    // stream
    streamWsMsg(data) {
        set({ messages: workflowStreamForHost(get().messages, data, get().chatId) as unknown as WorkflowMessage[] });
    },
    createSendMsg(msg) {
        set({ questions: [] });
        set((state) => ({
            messages:
                [...state.messages, {
                    ...bsMsgItem,
                    category: 'question',
                    message_id: generateUUID(8),
                    message: msg,
                    create_time: formatDate(new Date(), 'yyyy-MM-ddTHH:mm:ss')
                }]
        }))
    },
    insetSeparator(text) {
        const messages = get().messages
        // 避免重复提示会话结束
        if (messages[messages.length - 1]?.category === 'separator') return
        set((state) => ({
            messages: [...state.messages, {
                ...bsMsgItem,
                category: 'separator',
                message_id: generateUUID(8),
                message: text,
                create_time: formatDate(new Date(), 'yyyy-MM-ddTHH:mm:ss')
            }]
        }))
    },
    insetNodeRun(data) {
        if (['output', 'condition'].includes(data.message?.node_id.split('_')[0])) return
        set((state) => {
            const newChat = cloneDeep(state.messages);
            const { category, flow_id, chat_id, files, is_bot, liked, message, receiver, type, source, user_id } = data
            if (type === 'end') {
                return { messages: newChat.filter(msg => msg.message_id !== message.unique_id) }
            }
            newChat.push({
                category, flow_id, chat_id, message_id: message.unique_id, files, is_bot,
                message, receiver, source, user_id,
                liked: !!liked,
                end: false,
                sender: '',
                node_id: message?.node_id || '',
                create_time: formatDate(new Date(), 'yyyy-MM-ddTHH:mm:ss')
                // extra,
            })
            return { messages: newChat }
        })
    },
    overWsMsg(data) {
        // 删除所有未结束消息
        if (data.type === 'end_cover' && data.message) {
            console.log('触发安全审计,删除所有未结束消息 :>> ');
            data.category = "stream_msg"
            data.type = 'over'
            data.message_id = generateUUID(8)
            get().createWsMsg(data)
            setTimeout(() => {
                set((state) => ({ messages: state.messages.filter(msg => msg.end) }))
            }, 0);
        }
    },
    setShowGuideQuestion(bln: boolean) {
        set({ showGuideQuestion: bln })
    },
    clearMsgs() {
        set({ historyGeneration: get().historyGeneration + 1, hisMessages: [], messages: [], questions: [], inputForm: null, running: false, showGuideQuestion: false, historyEnd: true });
    },
    destory() {
        set({
            historyGeneration: get().historyGeneration + 1,
            chatId: '',
            questions: [],
            messages: [],
            inputForm: null,
            running: false,
            hisMessages: [],
            historyEnd: false,
            showGuideQuestion: false
        })
    },
    setInputForm(form) {
        set({ inputForm: form })
    },

    startNewRound(str) {
        get().insetSeparator(str)
        set((state) => ({ showGuideQuestion: true }))
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
return Object.assign(store, { services: createHistoryAdapter(store, 'workflow') });
};
export const { MessageStoreProvider, useMessageStore } = createMessageStoreScope(createMessageStore);



const bsMsgItem: any = {
    flow_id: '',
    chat_id: '',
    files: [],
    is_bot: false,
    receiver: '',
    source: 0,
    user_id: 0,
    end: true,
    sender: ''
}
