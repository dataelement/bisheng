import { useEffect } from "react";
import Chat from "./Chat";
import { useMessageStore } from "./messageStore";
import { getFlowApi } from "@/controllers/API/flow";
import { toast } from "@/components/bs-ui/toast/use-toast";

export default function ChatPane({ debug = false, autoRun = false, chatId, flow, wsUrl = '', test = false }: { autoRun?: boolean, chatId: string, flow: any, wsUrl?: string }) {
    const { changeChatId } = useMessageStore()

    useEffect(() => {
        chatId.startsWith('test') && changeChatId(chatId)
    }, [chatId])

    const getMessage = (action, { nodeId, msg, category, extra, files, source, message_id }) => {
        if (action === 'refresh_flow') {
            return getFlowApi(flow.id, 'v1').then(f => {
                const { data, ...other } = f
                const { edges, nodes, viewport } = data
                return {
                    action: 'init_data',
                    chat_id: chatId.startsWith('test') ? undefined : chatId,
                    flow_id: flow.id,
                    data: {
                        ...other,
                        edges,
                        nodes,
                        viewport
                    }
                }
            })
        }
        if (action === 'flowInfo') {
            return {
                flow_id: flow.id,
                chat_id: chatId.startsWith('test') ? undefined : chatId,
            }
        }
        if (action === 'getInputForm') {
            const node = flow.nodes.find(node => node.id === nodeId)
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
            const node = flow.nodes.find(node => node.id === nodeId)
            if (!node) {
                toast({
                    title: '提示',
                    variant: 'error',
                    description: '应用已更新，请重新发起会话'
                });
                return false;
            }
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
                flow_id: flow.id,
                chat_id: chatId.startsWith('test') ? undefined : chatId,
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
            flow_id: flow.id,
            data: flow
        }
    }

    return <Chat
        debug={debug}
        flow={flow}
        autoRun={autoRun}
        useName=''
        guideWord=''
        clear
        wsUrl={wsUrl}
        onBeforSend={getMessage}
    ></Chat>

};
