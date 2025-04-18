import { useEffect } from "react";
import Chat from "./Chat";
import { useMessageStore } from "./messageStore";

export default function ChatPane({ autoRun = false, chatId, flow, wsUrl = '', test = false }: { autoRun?: boolean, chatId: string, flow: any, wsUrl?: string }) {
    const { changeChatId } = useMessageStore()

    useEffect(() => {
        chatId.startsWith('test') && changeChatId(chatId)
    }, [chatId])

    const getMessage = (action, { nodeId, msg, category, extra, files, source, message_id }) => {

        const _flow = flow
        if (action === 'getInputForm') {
            const node = _flow.nodes.find(node => node.id === nodeId)
            if (node.data.tab.value === 'input') return null
            let form = null
            node.data.group_params.some(group => group.params.some(param => {
                if (param.tab === 'form') {
                    form = param
                    return true
                }
                return false
            }))
            return form
        }
        if (action === 'input') {
            const node = _flow.nodes.find(node => node.id === nodeId)
            const tab = node.data.tab.value
            let variable = ''
            node.data.group_params.some(group =>
                group.params.some(param => {
                    if (param.tab === tab) {
                        variable = param.key
                        return true
                    }
                    return false
                })
            )
            return {
                action,
                data: {
                    [nodeId]: {
                        data: {
                            [variable]: msg,
                            dialog_files_content: files
                        },
                        message: msg,
                        message_id,
                        category,
                        extra,
                        source
                    }
                }
            }
        }

        return {
            action,
            chat_id: chatId.startsWith('test') ? undefined : chatId,
            flow_id: _flow.id,
            data: _flow
        }
    }

    return <Chat
        flow={flow}
        autoRun={autoRun}
        useName=''
        guideWord=''
        clear
        wsUrl={wsUrl}
        onBeforSend={getMessage}
    ></Chat>

};
