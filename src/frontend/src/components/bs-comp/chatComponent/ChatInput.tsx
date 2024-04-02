import { GoIcon } from "@/components/bs-icons/go";
import { Button } from "@/components/bs-ui/button";
import { Textarea } from "@/components/bs-ui/input";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMessageStore } from "./messageStore";
import cloneDeep from "lodash-es/cloneDeep";
import { locationContext } from "@/contexts/locationContext";
import { PaperPlaneIcon, ReaderIcon } from "@radix-ui/react-icons";

export default function ChatInput({ inputForm, wsUrl, onBeforSend }) {
    const { toast } = useToast()
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)

    const [formShow, setFormShow] = useState(false)
    const [inputLock, setInputLock] = useState({ locked: false, reason: '' })

    const { messages, chatId, createSendMsg, createWsMsg, updateCurrentMessage, setWs, destory } = useMessageStore()
    const inputRef = useRef(null)

    useEffect(() => {
        if (!chatId) return
        createWebSocket(chatId).then(() => {
            const [wsMsg] = onBeforSend('', '')
            sendWsMsg(wsMsg)
        })
    }, [chatId])

    // 销毁
    useEffect(() => {
        return () => {
            destory()
            if (wsRef.current) {
                wsRef.current.close()
            }
        }
    }, [])

    const handleSendClick = async () => {
        const value = inputRef.current.value
        if (value.trim() === '') return

        inputRef.current.value = ''
        const [wsMsg, inputKey] = onBeforSend('', value)
        // msg to store
        createSendMsg(wsMsg.inputs, inputKey)
        // 锁定 input
        setInputLock({ locked: true, reason: '' })
        const chatid = chatId
        await createWebSocket(chatid)
        sendWsMsg(wsMsg)
    }

    const sendWsMsg = async (msg) => {
        try {
            wsRef.current.send(JSON.stringify(msg))
        } catch (error) {
            toast({
                title: 'There was an error sending the message',
                variant: 'error',
                description: error.message
            });
        }
    }

    const wsRef = useRef(null)
    const createWebSocket = (chatId) => {
        // 单例
        if (wsRef.current) return Promise.resolve('ok');
        const isSecureProtocol = window.location.protocol === "https:";
        const webSocketProtocol = isSecureProtocol ? "wss" : "ws";

        return new Promise((res, rej) => {
            try {
                const ws = new WebSocket(`${webSocketProtocol}://${wsUrl}&chat_id=${chatId}`)
                wsRef.current = ws
                // websocket linsen
                ws.onopen = () => {
                    console.log("WebSocket connection established!");
                    res('ok')
                };
                ws.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    const errorMsg = data.category === 'error' ? data.intermediate_steps : ''
                    // 异常类型处理，提示
                    if (errorMsg) return setInputLock({ locked: true, reason: errorMsg })
                    handleWsMessage(data)
                    // 群聊@自己时，开启input
                    if (data.type === 'end' && data.receiver?.is_self) {
                        setInputLock({ locked: true, reason: '' })
                    }
                }
                ws.onclose = (event) => {
                    wsRef.current = null
                    console.error('链接手动断开 event :>> ', event);
                    if ([1005, 1008].includes(event.code)) {
                        console.warn('即将废弃 :>> ');
                        setInputLock({ locked: true, reason: event.reason })
                    } else {
                        if (event.reason) {
                            toast({
                                title: '提示',
                                variant: 'error',
                                description: event.reason
                            });
                        }
                        setInputLock({ locked: false, reason: '' })
                    }
                };
                ws.onerror = (ev) => {
                    wsRef.current = null
                    console.error('链接异常error', ev);
                    toast({
                        title: `${t('chat.networkError')}:`,
                        variant: 'error',
                        description: [
                            t('chat.networkErrorList1'),
                            t('chat.networkErrorList2'),
                            t('chat.networkErrorList3')
                        ]
                    });
                    // reConnect(params)
                };
            } catch (err) {
                console.error('创建链接异常', err);
                rej(err)
            }
        })
    }

    // 接受 ws 消息
    const handleWsMessage = (data) => {
        if (Array.isArray(data) && data.length) return
        if (data.type === 'start') {
            createWsMsg(data)
        } else if (data.type === 'stream') {
            updateCurrentMessage({ message: data.message, thought: data.intermediate_steps })
        } else if (data.type === 'end') {
            updateCurrentMessage({
                ...data,
                end: true,
                thought: data.intermediate_steps || '',
                messageId: data.message_id,
                noAccess: false,
                liked: 0
            })
        } else if (data.type === "close") {
            setInputLock({ locked: false, reason: '' })
        }

    }

    // 监听重发消息事件
    useEffect(() => {
        const handleCustomEvent = (e) => {
            if (inputLock.locked) return
            const { send, message } = e.detail
            inputRef.current.value = message
            if (send) handleSendClick()
        }
        document.addEventListener('userResendMsgEvent', handleCustomEvent)
        return () => {
            document.removeEventListener('userResendMsgEvent', handleCustomEvent)
        }
    }, [inputLock.locked])

    // auto input height
    const handleTextAreaHeight = (e) => {
        const textarea = e.target
        textarea.style.height = 'auto'
        textarea.style.height = textarea.scrollHeight + 'px'
        // setInputEmpty(textarea.value.trim() === '')
    }

    return <div className="absolute bottom-0 w-full">
        <div className="relative">
            {/* form */}
            {
                formShow && <div className="relative">
                    <div className="absolute right-0 border bottom-2 bg-[#fff] px-4 py-2 rounded-md w-[50%] min-w-80">
                        {inputForm}
                    </div>
                </div>
            }
            {/* question */}
            <Textarea
                id="bs-send-input"
                ref={inputRef}
                rows={1}
                style={{ height: 56 }}
                disabled={inputLock.locked}
                onInput={handleTextAreaHeight}
                placeholder={inputLock.locked ? inputLock.reason : '请输入问题'}
                className="resize-none py-4 text-md min-h-6 max-h-[200px] scrollbar-hide text-gray-800"
                onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) handleSendClick()
                }}
            ></Textarea>
            <div className="flex gap-2 absolute right-3 bottom-4">
                <div
                    className={`w-6 h-6 rounded-sm hover:bg-gray-200 cursor-pointer flex justify-center items-center `}
                    onClick={() => setFormShow(!formShow)}
                ><ReaderIcon className={inputLock.locked && 'text-gray-200'}></ReaderIcon></div>
                <div
                    id="bs-send-btn"
                    className="w-6 h-6 rounded-sm hover:bg-gray-200 cursor-pointer flex justify-center items-center"
                    onClick={handleSendClick}
                ><PaperPlaneIcon className={inputLock.locked && 'text-gray-200'}></PaperPlaneIcon></div>
            </div>
        </div>
        <p className="text-center text-sm pt-2 pb-4 text-gray-400">{appConfig.dialogTips}</p>
    </div>
};
