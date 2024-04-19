import { message } from '@/components/bs-ui/toast/use-toast';
import { generateUUID } from '@/components/bs-ui/utils'
import { MessageDB, getChatHistory } from '@/controllers/API'
import { ChatMessageType } from '@/types/chat'
import { cloneDeep } from 'lodash'
import { create } from 'zustand'

/**
 * 会话消息管理
 */

type State = {
    running: boolean,
    /**
     * 会话 ID
     * 变更会触发 ws建立，解锁滚动
     */
    chatId: string,
    /** 没有更多历史纪录 */
    historyEnd: boolean,
    messages: ChatMessageType[]
    /**
     * 控制引导问题的显示状态
     */
    showGuideQuestion: boolean
}

type Actions = {
    loadHistoryMsg: (flowid: string, chatId: string) => Promise<void>;
    loadMoreHistoryMsg: (flowid: string) => Promise<void>;
    destory: () => void;
    createSendMsg: (inputs: any, inputKey?: string) => void;
    createWsMsg: (data: any) => void;
    updateCurrentMessage: (wsdata: any) => void;
    changeChatId: (chatId: string) => void;
    startNewRound: () => void;
    insetSeparator: (text: string) => void;
    insetSystemMsg: (text: string) => void;
    insetBsMsg: (text: string) => void;
    setShowGuideQuestion: (text: boolean) => void;
}


const handleHistoryMsg = (data: any[]): ChatMessageType[] => {
    const correctedJsonString = (str: string) => str
        // .replace(/\\([\s\S])|(`)/g, '\\\\$1$2') // 转义反斜线和反引号
        .replace(/\n/g, '\\n')                  // 转义换行符
        .replace(/\r/g, '\\r')                  // 转义回车符
        .replace(/\t/g, '\\t')                  // 转义制表符
        .replace(/'/g, '"');                    // 将单引号替换为双引号
    return data.map(item => {
        // let count = 0
        let { message, files, is_bot, intermediate_steps, ...other } = item
        try {
            message = message && message[0] === '{' ? JSON.parse(message) : message || ''
        } catch (e) {
            // 未考虑的情况暂不处理
            console.error('消息 to JSON error :>> ', e);
        }
        return {
            ...other,
            chatKey: typeof message === 'string' ? undefined : Object.keys(message)[0],
            end: true,
            files: files ? JSON.parse(files) : [],
            isSend: !is_bot,
            message,
            thought: intermediate_steps,
            noAccess: true
        }
    })
}

let currentChatId = ''
const runLogsTypes = ['tool', 'flow', 'knowledge']
export const useMessageStore = create<State & Actions>((set, get) => ({
    running: false,
    chatId: '',
    messages: [],
    historyEnd: false,
    showGuideQuestion: false,
    setShowGuideQuestion(bln: boolean) {
        set({ showGuideQuestion: bln })
    },
    async loadHistoryMsg(flowid, chatId) {
        const res = await getChatHistory(flowid, chatId, 30, 0)
        const msgs = handleHistoryMsg(res)
        currentChatId = chatId
        set({ historyEnd: false, messages: msgs.reverse() })
    },
    async loadMoreHistoryMsg(flowid) {
        if (get().running) return // 会话进行中禁止加载more历史
        if (get().historyEnd) return // 没有更多历史纪录
        const chatId = get().chatId
        const prevMsgs = get().messages
        // 最后一条消息id不存在，忽略 loadmore
        if (!prevMsgs[0]?.id) return
        const res = await getChatHistory(flowid, chatId, 10, prevMsgs[0]?.id || 0)
        // 过滤非同一会话消息
        if (res[0]?.chat_id !== currentChatId) {
            return console.warn('loadMoreHistoryMsg chatId not match, ignore')
        }
        const msgs = handleHistoryMsg(res)
        if (msgs.length) {
            set({ messages: [...msgs.reverse(), ...prevMsgs] })
        } else {
            set({ historyEnd: true })
        }
    },
    destory() {
        set({ chatId: '', messages: [] })
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
                    user_name: ""
                }]
        }))
    },
    // start
    createWsMsg(data) {
        console.log('change createWsMsg');
        set((state) => {
            let newChat = cloneDeep(state.messages);
            newChat.push({
                isSend: false,
                message: runLogsTypes.includes(data.category) ? JSON.parse(data.message) : '',
                chatKey: '',
                thought: data.intermediate_steps || '',
                category: data.category || '',
                files: [],
                end: false,
                user_name: '',
                extra: data.extra
            })
            return { messages: newChat }
        })
    },
    // stream end
    updateCurrentMessage(wsdata) {
        // console.log( wsdata.chat_id, get().chatId);
        // if (wsdata.end) {
        //     debugger
        // }
        console.log('change updateCurrentMessage');
        const messages = get().messages
        const isRunLog = runLogsTypes.includes(wsdata.category);
        // run log类型存在嵌套情况，使用 extra 匹配 currentMessage; 否则取最近
        const currentMessageIndex = isRunLog ?
            messages.findLastIndex((msg) => msg.extra === wsdata.extra)
            : messages.findLastIndex((msg) => !runLogsTypes.includes(msg.category))
        const currentMessage = messages[currentMessageIndex]

        const newCurrentMessage = {
            ...currentMessage,
            ...wsdata,
            id: isRunLog ? wsdata.extra : wsdata.messageId, // 每条消息必唯一
            message: isRunLog ? JSON.parse(wsdata.message) : currentMessage.message + wsdata.message,
            thought: currentMessage.thought + (wsdata.thought ? `${wsdata.thought}\n` : ''),
            files: wsdata.files || null,
            category: wsdata.category || '',
            source: wsdata.source
        }

        messages[currentMessageIndex] = newCurrentMessage
        // 会话特殊处理，兼容后端的缺陷
        if (!isRunLog) {
            // start - end 之间没有内容删除load
            if (newCurrentMessage.end && !(newCurrentMessage.files.length || newCurrentMessage.thought || newCurrentMessage.message)) {
                messages.pop()
            }
            // 无 messageid 删除
            // if (newCurrentMessage.end && !newCurrentMessage.id) {
            //     messages.pop()
            // }
            // 删除重复消息
            const prevMessage = messages[currentMessageIndex - 1];
            if (prevMessage
                && prevMessage.message === newCurrentMessage.message
                && prevMessage.thought === newCurrentMessage.thought) {
                const removedMsg = messages.pop()
                // 使用最后一条的信息作为准确信息
                Object.keys(prevMessage).forEach((key) => {
                    prevMessage[key] = removedMsg[key]
                })
            }
        }
        set((state) => ({ messages: [...messages] }))
    },
    changeChatId(chatId) {
        set((state) => ({ chatId }))
    },
    startNewRound() {
        get().insetSeparator('配置已更新')
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
}))


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