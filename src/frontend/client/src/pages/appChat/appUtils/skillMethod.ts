import { formatDate } from "~/utils";

const runLogsTypes = ['tool', 'flow', 'knowledge']
// 兼容处理技能和助手
export const SkillMethod = {
    /** 获取input发送参数 */
    getSendParam: ({ tabs, flow, chatId, message }) => {
        const msgData = {
            chatHistory: [],
            flow_id: flow.id,
            chat_id: chatId,
            name: flow.name,
            description: flow.description || flow.desc,
            inputs: {}
        } as any
        if (flow.flow_type === 1) {
            let inputs = tabs[flow.id].formKeysData.input_keys;
            const input = inputs.find((el: any) => !el.type)
            const inputKey = input ? Object.keys(input)[0] : '';
            if (message) msgData.inputs = { ...input, [inputKey]: message }
        } else {
            msgData.inputs = {
                data: {
                    chatId,
                    id: flow.id,
                    type: 5
                },
                input: message
            }
        }
        // if (formDataRef.current?.length) {
        //     msgData.inputs.data = formDataRef.current
        //     formDataRef.current = null
        // }
        // if (action === 'continue') msgData.action = action
        return msgData
    },
    /** start参数 */
    getStartParam: (data: any, chatId) => {
        data.message = runLogsTypes.includes(data.category) ? JSON.parse(data.message) : '';
        data.thought = data.intermediate_steps || ''
        data.category = runLogsTypes.includes(data.category) ? data.category : 'stream_msg'
        data.chat_id = chatId
        return data
    },
    /** 更新消息 */
    updateStreamMessage: (data: any, chatId, messages: any, cover?: boolean) => {
        const wsdata = data.type === 'stream' ? {
            chat_id: chatId,
            message: data.message,
            category: runLogsTypes.includes(data.category) ? data.category : 'stream_msg',
            thought: data.intermediate_steps
        } : {
            ...data,
            chat_id: chatId,
            end: true,
            thought: data.intermediate_steps || '',
            messageId: data.message_id,
            noAccess: false,
            liked: 0,
            category: runLogsTypes.includes(data.category) ? data.category : 'stream_msg',
            create_time: formatDate(new Date(), 'yyyy-MM-ddTHH:mm:ss')
        }
        const isRunLog = runLogsTypes.includes(wsdata.category);
        // run log类型存在嵌套情况，使用 extra 匹配 currentMessage; 否则取最近
        let currentMessageIndex = 0
        for (let i = messages.length - 1; i >= 0; i--) {
            if (!messages[i].is_bot) break;
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
        let reasoning_log = currentMessage.reasoning_log || ''
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
            if (wsdata.type === 'end_cover' && prevMessage.is_bot) {
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

        return [...messages]
    }
}