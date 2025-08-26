/**
 * websocket辅助函数
 */
import { produce } from "immer"
import { useMemo } from "react"
import { useRecoilState, useRecoilValue } from "recoil"
import { Chat } from "~/@types/chat"
import { baseMsgItem } from "~/api/apps"
import { formatDate, generateUUID } from "~/utils"
import { flowType } from "."
import { bishengConfState, chatIdState, chatsState, currentChatState, currentRunningState, runningState } from "./store/atoms"
import { emitAreaTextEvent, EVENT_TYPE } from "./useAreaText"
import { SkillMethod } from "./appUtils/skillMethod"

export default function useChatHelpers() {
    const chatState = useRecoilValue(currentChatState)
    const runState = useRecoilValue(currentRunningState)
    const [bishengConfig] = useRecoilState(bishengConfState)
    const [_, setChats] = useRecoilState(chatsState)
    const [__, setRunningState] = useRecoilState(runningState)
    const [chatId] = useRecoilState(chatIdState)

    const wsUrl = useMemo(() => {
        if (!chatState) return ""

        const { flow } = chatState;
        const type = Number(flow.flow_type)
        const host = bishengConfig?.websocket_url || window.location.host;
        const basePath = __APP_ENV__.BASE_URL;

        const routeConfig = {
            [flowType.SKILL]: `${host}${basePath}/api/v1/chat/${flow.id}?type=L1`,
            [flowType.ASSISTANT]: `${window.location.host}${basePath}/api/v1/assistant/chat/${flow.id}`,
            [flowType.WORK_FLOW]: `${host}${basePath}/api/v1/workflow/chat/${flow.id}?chat_id=${chatId}`
        };

        return routeConfig[type] || '';
    }, [chatState, chatId, bishengConfig])

    // handleMsgError
    const handleMsgError = (errorMsg: string) => {
        setRunningState((prev) => ({
            ...prev,
            [chatId]: {
                ...prev[chatId],
                running: false,
                showStop: false,
                showUpload: false,
                inputDisabled: true,
                error: errorMsg,
            },
        }))
    }

    // 显示停止按钮
    const stopShow = (show: boolean) => {
        setRunningState((prev) => ({
            ...prev,
            [chatId]: {
                ...prev[chatId],
                running: true,
                showStop: show,
            },
        }))
    }

    // 唤起输入(表单输入，文本输入)
    const showInputForm = (inputSchema) => {
        const { tab, value } = inputSchema

        if (tab === "dialog_input") {
            const schemaItem = value?.find((el) => el.key === "dialog_file_accept")
            const fileAccept = schemaItem?.value
            emitAreaTextEvent({ action: EVENT_TYPE.FILE_ACCEPTS, chatId, fileAccept })
        }

        const runstate = tab === "form_input" ? { inputDisabled: true, inputForm: inputSchema } : { inputDisabled: false }

        setRunningState((prev) => ({
            ...prev,
            [chatId]: {
                ...prev[chatId],
                showStop: false,
                ...runstate,
            },
        }))
    }

    const showGuideQuestion = (chatid, question) => {
        setRunningState((prev) => ({
            ...prev,
            [chatid]: {
                ...prev[chatid],
                guideWord: question,
            },
        }))
    }
    // const stop = () => {
    // }

    // 更新消息
    const message = {
        createNodeMsg: (chatid: string, data: any) => {
            if (['output', 'condition'].includes(data.message?.node_id.split('_')[0])) return

            setChats((prev) =>
                updateChatMessages(prev, chatid, (messages) => {
                    const { category, flow_id, chat_id, files, is_bot, liked, message, receiver, type, source, user_id } = data

                    if (type === "end") {
                        return messages.filter((msg) => msg.id !== message.unique_id)
                    }

                    return [
                        ...messages,
                        {
                            category,
                            flow_id,
                            chat_id,
                            id: message.unique_id,
                            files,
                            is_bot,
                            message,
                            receiver,
                            source,
                            user_id,
                            liked: !!liked,
                            end: false,
                            sender: "",
                            node_id: message?.node_id || "",
                            create_time: formatDate(new Date(), "yyyy-MM-ddTHH:mm:ss"),
                        },
                    ]
                }),
            )
        },
        createMsg: (chatid: string, data: any) => {
            setChats((prev) =>
                updateChatMessages(prev, chatid, (messages) => {
                    const {
                        category,
                        flow_id,
                        chat_id,
                        message_id,
                        files,
                        is_bot,
                        extra,
                        liked,
                        message,
                        receiver,
                        type,
                        source,
                        user_id,
                        reasoning_log,
                        thought
                    } = data

                    const messageId = message_id || (category === "guide_word" ? generateUUID(4) : "")
                    const filteredMessages = deduplicateMessages(messages, message_id)

                    return [
                        ...filteredMessages,
                        {
                            category,
                            flow_id,
                            chat_id,
                            id: messageId,
                            files,
                            is_bot,
                            message,
                            receiver,
                            source,
                            user_id,
                            liked: !!liked,
                            end: type === "over",
                            sender: "",
                            node_id: message?.node_id || "",
                            create_time: formatDate(new Date(), "yyyy-MM-ddTHH:mm:ss"),
                            extra,
                            reasoning_log,
                            thought
                        },
                    ]
                }),
            )
        },
        streamMsg: (chatid: string, data: any) => {
            setChats((prev) =>
                updateChatMessages(prev, chatid, (messages) => {
                    const { unique_id, output_key, reasoning_content } = data.message
                    const messageId = unique_id + output_key
                    const currentMessageIndex = messages.findIndex((msg) => msg.id === messageId)

                    if (currentMessageIndex === -1) {
                        // Create new message
                        const { category, flow_id, chat_id, files, is_bot, extra, liked, receiver, type, source, user_id } = data
                        const message = data.message.msg
                        const reasoning_log = reasoning_content || ""

                        const filteredMessages = deduplicateMessages(messages, messageId)
                        return [
                            ...filteredMessages,
                            {
                                category,
                                flow_id,
                                chat_id,
                                id: messageId,
                                files,
                                is_bot,
                                message,
                                receiver,
                                source,
                                user_id,
                                liked: !!liked,
                                end: type === "over",
                                sender: "",
                                node_id: data.message?.node_id || "",
                                create_time: formatDate(new Date(), "yyyy-MM-ddTHH:mm:ss"),
                                extra,
                                reasoning_log,
                            },
                        ]
                    } else {
                        // Update existing message
                        const currentMsg = messages[currentMessageIndex]
                        const updatedMessages = [...messages]
                        updatedMessages[currentMessageIndex] = {
                            ...currentMsg,
                            id: data.type === "end" ? data.message_id : currentMsg.id,
                            message: data.type === "end" ? data.message.msg : currentMsg.message + data.message.msg,
                            reasoning_log: reasoning_content
                                ? currentMsg.reasoning_log + reasoning_content
                                : currentMsg.reasoning_log,
                            create_time: formatDate(new Date(), "yyyy-MM-ddTHH:mm:ss"),
                            source: data.source,
                            end: data.type === "end",
                        }
                        return updatedMessages
                    }
                }),
            )
        },
        skillStreamMsg: (chatid: string, data: any) => {
            setChats((prev) =>
                updateChatMessages(prev, chatid, (messages) => {
                    return SkillMethod.updateStreamMessage(data, chatid, messages,
                        data.type === 'end_cover' && data.category === 'anwser'
                    )
                })
            )
        },
        skillCloseMsg: () => {
            setRunningState((prev) => ({
                ...prev,
                [chatId]: {
                    ...prev[chatId],
                    running: false,
                    inputDisabled: false,
                    inputForm: true,
                    showStop: false
                },
            }))
        },
        endMsg: (chatid: string, data: any) => {
            // 删除所有未结束消息
            if (data.type === "end_cover" && data.message) {
                console.log("触发安全审计,删除所有未结束消息")
                data.category = "stream_msg"
                data.type = "over"
                data.id = generateUUID(8)
                message.createMsg(chatid, data)

                // Use setTimeout to avoid blocking
                setTimeout(() => {
                    setChats((prev) => updateChatMessages(prev, chatId, (messages) => messages.filter((msg) => msg.end)))
                }, 0)
            }
        },
        insetSeparator: (chatid: string, msg: string) => {
            setChats((prev) =>
                updateChatMessages(prev, chatid, (messages) => {
                    if (messages[messages.length - 1]?.category === "separator") return messages

                    return [
                        ...messages,
                        {
                            ...baseMsgItem,
                            category: "divider",
                            id: generateUUID(8),
                            message: msg,
                            create_time: formatDate(new Date(), "yyyy-MM-ddTHH:mm:ss"),
                        },
                    ]
                }),
            )
        },
        createSendMsg: (msg: string) => {
            setChats((prev) =>
                updateChatMessages(prev, chatId, (messages) => [
                    ...messages,
                    {
                        ...baseMsgItem,
                        category: "question",
                        id: generateUUID(8),
                        message: msg,
                        create_time: formatDate(new Date(), "yyyy-MM-ddTHH:mm:ss"),
                    },
                ]),
            )
        },
    }

    return {
        wsUrl,
        chatId,
        running: runState?.running,
        message,
        flow: chatState?.flow,
        stopShow,
        handleMsgError,
        showInputForm,
        showGuideQuestion
    }
};


const updateChatMessages = (
    chats: Record<string, Chat>,
    chatId: string,
    updater: (messages: any[]) => any[],
): Record<string, Chat> => {
    return produce(chats, (draft) => {
        if (draft[chatId]) {
            const currentMessages = draft[chatId].messages || []
            const updatedMessages = updater(currentMessages)

            // Only update if messages actually changed
            if (updatedMessages !== currentMessages) {
                draft[chatId].messages = updatedMessages
            }
        }
    })
}

export const deduplicateMessages = (messages: any[], messageId: string): any[] => {
    if (!messageId) return messages

    const seenIds = new Set<string>()
    return messages.filter((msg) => {
        const shouldExclude = msg.id === messageId && msg.his
        if (shouldExclude) return false

        if (seenIds.has(msg.id)) return false
        seenIds.add(msg.id)
        return true
    })
}