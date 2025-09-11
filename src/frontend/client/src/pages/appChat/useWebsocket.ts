"use client"
import { useEffect, useRef } from "react"
import { useRecoilState } from "recoil"
import { NotificationSeverity } from "~/common"
import { useToast } from "~/hooks"
import { SkillMethod } from "./appUtils/skillMethod"
import { submitDataState } from "./store/atoms"
import { ERROR_CODES } from "./store/constants"

export const AppLostMessage = '当前应用已被删除'
const wsMap = new Map<string, WebSocket>()
// 会话运行时信息
const sessionInfoMap = new Map<string, any>()

export const enum ActionType {
    INIT_DATA = 'init_data',
    INPUT = 'input',
    CHECK_STATUS = 'check_status',
    STOP = 'stop',
    RESTART = 'restart',
    FORM_SUBMIT = 'form_submit',
    MESSAGE_INPUT = 'message_input',
    SKILL_INPUT = 'skill_input',
    SKILL_FORM_SUBMIT = 'skill_form_submit'
}

const restartCallBack: any = { current: null } // 用于存储重启回调函数

export const useWebSocket = (helpers) => {
    const { showToast } = useToast();
    const [submitData, setSubmitData] = useRecoilState(submitDataState)

    const websocket = wsMap.get(helpers.chatId)
    const currentChatId = useCurrentChatId(helpers.chatId)

    // 连接WebSocket
    const connect = (callBack) => {
        if (websocket) return
        if (!helpers.wsUrl) return
        if (helpers.appLost === AppLostMessage) return

        const isSecureProtocol = window.location.protocol === "https:";
        const webSocketProtocol = isSecureProtocol ? "wss" : "ws";
        const ws = new WebSocket(`${webSocketProtocol}://${helpers.wsUrl}`)
        wsMap.set(helpers.chatId, ws)

        ws.onopen = () => {
            console.log("WebSocket connection established!");
            helpers.clearError()
            if (helpers.flow.flow_type === 10) {
                // 工作流初始化
                // console.log('helpers.flow :>> ', helpers.flow);
                const { data, ...flow } = helpers.flow
                const msg = {
                    action: helpers.flow.isNew ? ActionType.INIT_DATA : ActionType.CHECK_STATUS,
                    chat_id: helpers.chatId,
                    flow_id: helpers.flow.id,
                    data: { ...flow, ...data },
                }
                ws?.send(JSON.stringify(msg))
            } else {
                // 助手初始化
                const msg = {
                    chatHistory: [],
                    chat_id: helpers.chatId,
                    flow_id: helpers.flow.id,
                    inputs: {
                        data: helpers.flow.flow_type === 5 ? {
                            id: helpers.flow.id,
                            chatId: helpers.chatId,
                            type: helpers.flow.flow_type,
                        } : undefined
                    },
                    name: helpers.flow.name,
                    description: helpers.flow.description
                }
                ws?.send(JSON.stringify(msg))
            }

            callBack?.(ws)
        }

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data)
                console.log('data :>> ', data);
                handleMessages(data)
            } catch (error) {
                console.error("WebSocket message parse error:", error)
            }
        }

        ws.onclose = (event) => {
            console.log('close chatId:>> ', helpers.chatId);
            console.error('ws close :>> ', event);
            helpers.handleMsgError(event.reason)
            // todo 错误消息写入消息下面
        }

        ws.onerror = (error) => {
            console.error('链接异常error', helpers.chatId, error);
            helpers.handleMsgError('')
        }
    }
    const handleMessages = (data) => {
        // 过滤无效数据
        if ((data.category === 'end_cover' && data.type !== 'end_cover')) {
            return
        }

        if (data.type === 'begin') {
            // 工作流input会有再begin之前出现的情况
            // helpers.stopShow(true)
        } else if (data.type === 'close' && data.category === 'processing') {
            helpers.stopShow(false)
        }

        // messages
        if (data.category === 'error') {
            const { code, message } = data.message
            helpers.handleMsgError(data.intermediate_steps || '')

            const errorMsg = code == 500 ? message : ERROR_CODES[code]
            showToast({
                message: errorMsg,
                severity: NotificationSeverity.ERROR,
            })
            return
        } else if (data.category === 'node_run') {
            return helpers.message.createNodeMsg(helpers.chatId, data)
        } else if (data.category === 'guide_word') {
            data.message.msg = data.message.guide_word
        } else if (data.category === 'input') {
            const { node_id, input_schema } = data.message
            sessionInfoMap.set(helpers.chatId, { node_id, message_id: data.message_id })
            // 待用户输入
            helpers.showInputForm({ ...input_schema, node_id })
            return
        } else if (data.category === 'guide_question') {
            return helpers.showGuideQuestion(helpers.chatId, data.message.guide_question.filter(q => q))
        } else if (data.category === 'stream_msg') {
            helpers.message.streamMsg(helpers.chatId, data)
        } else if (data.category === 'end_cover' && data.type === 'end_cover') {
            // helpers.handleMsgError('')
            sendWsMsg({ action: 'close' })
            return helpers.message.endMsg(helpers.chatId, data)
        }

        /***** 技能 & 助手 start******/
        if (helpers.flow.flow_type !== 10) {
            if (Array.isArray(data) && data.length) return
            if (data.type === 'start') {
                const _data = SkillMethod.getStartParam(data, helpers.chatId)
                helpers.message.createMsg(helpers.chatId, _data)
            } else if (data.type === 'stream') {
                helpers.message.skillStreamMsg(helpers.chatId, data)
            }
            if (['end', 'end_cover'].includes(data.type) && data.receiver?.is_self) {
                // 群聊@自己时
                helpers.showInputForm({})
            } else if (['end', 'end_cover'].includes(data.type)) {
                // todo 无未闭合的消息，先创建（补一条start）  工具类除外
                helpers.message.skillStreamMsg(helpers.chatId, data)
            } else if (data.type === 'close') {
                helpers.message.skillCloseMsg()
            }

            return
        }
        /***** 技能 end******/
        if (data.type === 'close' && data.category === 'processing') {
            helpers.message.insetSeparator(helpers.chatId, '本轮会话已结束')
            // helpers.handleMsgError('')
            // 重启会话按钮,接收close确认后端处理结束后重启会话
            if (restartCallBack.current) {
                restartCallBack.current()
                restartCallBack.current = null
            }
        } else if (data.type === 'over') {
            helpers.message.createMsg(helpers.chatId, data)
        }
    }
    useEffect(() => {
        connect()

        return () => {
            // 后台运行的会话结束后，断开WebSocket连接
            if (currentChatId !== helpers.chatId) {
                // 断开WebSocket连接
                if (websocket && !helpers.running) {
                    console.log('ws close', currentChatId, helpers.chatId)
                    websocket.close()
                    wsMap.delete(helpers.chatId)
                }
            }
        }
    }, [helpers.chatId, helpers.running])

    const sendWsMsg = async (msg) => {
        try {
            if (websocket) {
                websocket.send(JSON.stringify(msg))
            } else {
                connect((_websocket) => {
                    _websocket.send(JSON.stringify(msg))
                })
            }
        } catch (error: any) {
            showToast({
                message: error.message,
                severity: NotificationSeverity.ERROR,
            })
        }
    }

    // 监听submitData变化，发送消息（必须在当前会话调用）
    useEffect(() => {
        if (submitData
            && (submitData.action === 'skill_input' || websocket && websocket.readyState === WebSocket.OPEN)) {
            const action = submitData.action

            switch (action) {
                case ActionType.RESTART:
                    sendWsMsg({ action: 'stop' })
                    const { data, ...other } = submitData.flow
                    const flow = { ...other, edges: data.edges, nodes: data.nodes, viewport: data.viewport }
                    restartCallBack.current = () => {
                        sendWsMsg({
                            action: ActionType.INIT_DATA,
                            chat_id: submitData.chatId,
                            flow_id: flow.id,
                            data: flow,
                        })
                    }
                    break
                case ActionType.INPUT:
                    const sessionInfo = sessionInfoMap.get(helpers.chatId)
                    const node = submitData.flow.data.nodes.find(node => node.id === sessionInfo?.node_id)
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

                    let message = submitData.input
                    let filePath = []
                    // 文件拼接入消息
                    if (submitData.files?.length) {
                        const [_filePath, fileNames] = submitData.files.reduce((acc, cur) => {
                            acc[0].push(cur.path)
                            acc[1].push(cur.name)
                            return acc
                        }, [[], []])
                        filePath = _filePath
                        // 文件拼接入消息
                        const _value = submitData.input
                        message = fileNames.length > 0 ? fileNames.join('\n') + '\n' + _value : _value;
                    }

                    sendWsMsg({
                        action: 'input',
                        chat_id: submitData.chatId,
                        flow_id: submitData.flow.id,
                        data: {
                            [sessionInfo?.node_id]: {
                                data: {
                                    [variable]: message,
                                    dialog_files_content: filePath
                                },
                                message,
                                message_id: sessionInfo.message_id,
                                category: 'question',
                                extra: '',
                                source: 0
                            }
                        },
                    })

                    helpers.message.createSendMsg(message)
                    break
                case ActionType.SKILL_INPUT:
                    sendWsMsg(submitData.data)
                    helpers.message.createSendMsg(submitData.input)
                    break;
                case ActionType.FORM_SUBMIT:
                    sendWsMsg({
                        action: 'input',
                        chat_id: submitData.chatId,
                        flow_id: submitData.flowId,
                        data: {
                            [submitData.nodeId!]: {
                                data: submitData.data,
                                message: submitData.input,
                                message_id: sessionInfoMap.get(helpers.chatId).message_id,
                                category: 'question',
                                extra: '',
                                source: 0
                            }
                        },
                    })

                    helpers.message.createSendMsg(submitData.input)
                    break;
                case ActionType.SKILL_FORM_SUBMIT:
                    sendWsMsg(submitData.data)

                    helpers.message.createSendMsg(submitData.input)
                    break;
                case ActionType.MESSAGE_INPUT:
                    sendWsMsg({
                        action: 'input',
                        chat_id: submitData.chatId,
                        flow_id: submitData.flowId,
                        data: {
                            [submitData.data.nodeId!]: {
                                data: submitData.data.data,
                                message: submitData.data.message,
                                message_id: submitData.data.msgId
                            }
                        },
                    })
                    break;
                case ActionType.STOP:
                    sendWsMsg({ action: 'stop' })
                    break;
            }
            setSubmitData(null)
        }
    }, [submitData])
}


const useCurrentChatId = (chatId) => {
    const currentChatIdRef = useRef<string | null>(null)
    useEffect(() => {
        currentChatIdRef.current = chatId
    }, [chatId])

    return currentChatIdRef.current
}

