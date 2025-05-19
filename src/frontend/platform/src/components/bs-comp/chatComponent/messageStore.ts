import { getChatHistory } from '@/controllers/API';
import { ChatMessageType } from '@/types/chat';
import { formatDate } from '@/util/utils';
import cloneDeep from 'lodash-es/cloneDeep';
import { create } from 'zustand';

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
    /** 历史回话独立存储 */
    hisMessages: ChatMessageType[]
    /**
     * 控制引导问题的显示状态
     */
    showGuideQuestion: boolean
}

type Actions = {
    loadHistoryMsg: (flowid: string, chatId: string, data: { appendHistory: boolean, lastMsg: string }) => Promise<void>;
    loadMoreHistoryMsg: (flowid: string, appendHistory: boolean) => Promise<void>;
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
    clearMsgs: () => void;
}


const handleHistoryMsg = (data: any[]): ChatMessageType[] => {
    const correctedJsonString = (str: string) => str
        // .replace(/\\([\s\S])|(`)/g, '\\\\$1$2') // 转义反斜线和反引号
        .replace(/\n/g, '\\n')                  // 转义换行符
        .replace(/\r/g, '\\r')                  // 转义回车符
        .replace(/\t/g, '\\t')                  // 转义制表符
        .replace(/'/g, '"');                    // 将单引号替换为双引号
    const newData = data.filter(item =>
        ['answer', 'question', 'processing', 'system', 'report', 'tool', 'knowledge', 'divider', 'flow', 'reasoning_answer'].includes(item.category)
    )
    return newData.map(item => {
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
    hisMessages: [],
    historyEnd: false,
    showGuideQuestion: false,
    setShowGuideQuestion(bln: boolean) {
        set({ showGuideQuestion: bln })
    },
    async loadHistoryMsg(flowid, chatId, { appendHistory, lastMsg }) {
        const res = await getChatHistory(flowid, chatId, 30, 0)
        const msgs = handleHistoryMsg(res)
        currentChatId = chatId
        const hisMessages = appendHistory ? [] : msgs.reverse()
        if (hisMessages.length) {
            hisMessages.push({
                ...bsMsgItem,
                id: Math.random() * 1000000,
                category: 'divider',
                message: lastMsg,
            })
        }
        set({
            historyEnd: false,
            messages: appendHistory ? msgs.reverse() : [],
            hisMessages
        })
    },
    async loadMoreHistoryMsg(flowid, appendHistory) {
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
            set({ [appendHistory ? 'messages' : 'hisMessages']: [...msgs.reverse(), ...prevMsgs] })
        } else {
            set({ historyEnd: true })
        }
    },
    clearMsgs() {
        setTimeout(() => {
            set({ hisMessages: [], messages: [], historyEnd: true })
        }, 0);
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
                    user_name: "",
                    create_time: formatDate(new Date(), 'yyyy-MM-ddTHH:mm:ss')
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
                extra: data.extra,
                reasoning_log: ''
            })
            return { messages: newChat }
        })
    },
    // stream end
    updateCurrentMessage(wsdata, cover = false) {
        // console.log( wsdata.chat_id, get().chatId);
        // if (wsdata.end) {
        //     debugger
        // }
        console.log('change updateCurrentMessage');
        const messages = get().messages
        const isRunLog = runLogsTypes.includes(wsdata.category);
        // run log类型存在嵌套情况，使用 extra 匹配 currentMessage; 否则取最近
        let currentMessageIndex = 0
        for (let i = messages.length - 1; i >= 0; i--) {
            if (messages[i].isSend) break;
            if (isRunLog && messages[i].extra === wsdata.extra) {
                currentMessageIndex = i;
                break;
            } else if (!isRunLog && !runLogsTypes.includes(messages[i].category)) {
                currentMessageIndex = i;
                break;
            } else if (wsdata.type === 'end_cover' && messages[i].category === 'tool') {
                currentMessageIndex = i;
                break;
            }
        }
        const currentMessage = messages[currentMessageIndex]
        // deepseek
        let message = ''
        let reasoning_log = currentMessage.reasoning_log
        if (isRunLog) {
            message = JSON.parse(wsdata.message)
        } else if (typeof wsdata.message !== 'string' && wsdata.message && 'reasoning_content' in wsdata.message) {
            message = currentMessage.message + (wsdata.message.content || '')
            reasoning_log += (wsdata.message.reasoning_content || '')
        } else {
            message = currentMessage.message + (wsdata.message || '')
        }

        // 敏感词特殊处理
        if (wsdata.type === 'end_cover' && currentMessage.category === 'tool') {
            messages.forEach((msg) => {
                msg.end = true // 闭合所有会话
            })
            cover = false
        }
        const newCurrentMessage = {
            ...currentMessage,
            ...wsdata,
            id: currentMessage.id || (isRunLog ? wsdata.extra : wsdata.messageId), // 每条消息必唯一
            message,
            reasoning_log,
            thought: currentMessage.thought + (wsdata.thought ? `${wsdata.thought}\n` : ''),
            files: wsdata.files || [],
            category: wsdata.category || '',
            source: wsdata.source
        }
        // 无id补上（如文件解析完成消息，后端无返回messageid）
        if (!newCurrentMessage.id) {
            newCurrentMessage.id = Math.random() * 1000000
            // console.log('msg:', newCurrentMessage);
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

            // hack 
            if (wsdata.type === 'end_cover' && !prevMessage.isSend) {
                cover = true
            }

            // 有思考不覆盖 只覆盖message,保留思考
            if (prevMessage?.reasoning_log) {
                if ((prevMessage
                    && prevMessage.message === newCurrentMessage.message
                    && prevMessage.thought === newCurrentMessage.thought)
                    || cover) {
                    const removedMsg = messages.pop()
                    prevMessage.message = removedMsg.message
                }
            } else {
                if ((prevMessage
                    && prevMessage.message === newCurrentMessage.message
                    && prevMessage.thought === newCurrentMessage.thought)
                    || cover) {
                    const removedMsg = messages.pop()
                    // 使用最后一条的信息作为准确信息
                    Object.keys(prevMessage).forEach((key) => {
                        prevMessage[key] = removedMsg[key]
                    })
                }
            }

        }
        set((state) => ({ messages: [...messages] }))
    },
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