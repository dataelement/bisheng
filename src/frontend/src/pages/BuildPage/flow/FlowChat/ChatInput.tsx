import { ClearIcon } from "@/components/bs-icons/clear";
import { FormIcon } from "@/components/bs-icons/form";
import { SendIcon } from "@/components/bs-icons/send";
import { Button } from "@/components/bs-ui/button";
import { Textarea } from "@/components/bs-ui/input";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { locationContext } from "@/contexts/locationContext";
import { formatDate } from "@/util/utils";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
// import GuideQuestions from "./GuideQuestions";
// import { useMessageStore } from "./messageStore";
import { CirclePause } from "lucide-react";
import { useMessageStore } from "./messageStore";
import GuideQuestions from "./GuideQuestions";
import InputForm from "./InputForm";

export default function ChatInput({ clear, form, wsUrl, onBeforSend }) {
    const { toast } = useToast()
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)

    const [inputLock, setInputLock] = useState({ locked: true, reason: '' })
    const questionsRef = useRef(null)
    const inputNodeIdRef = useRef('') // 当前输入框节点id
    const [inputForm, setInputForm] = useState(null) // input表单

    const [showWhenLocked, setShowWhenLocked] = useState(false) // 强制开启表单按钮，不限制于input锁定

    const { messages, hisMessages, chatId, createSendMsg, createWsMsg, streamWsMsg, insetSeparator, destory, insetNodeRun, setShowGuideQuestion } = useMessageStore()
    console.log('ui messages :>> ', messages);

    const currentChatIdRef = useRef(null)
    const inputRef = useRef(null)
    const continueRef = useRef(false)
    // 停止状态
    const [stop, setStop] = useState({
        show: false,
        disable: false
    })
    const [autogenStop, setAutogenStop] = useState(false)
    /**
     * 记录会话切换状态，等待消息加载完成时，控制表单在新会话自动展开
     */
    const changeChatedRef = useRef(false)
    useEffect(() => {
        // console.log('message msg', messages, form);

        if (changeChatedRef.current) {
            changeChatedRef.current = false
            // 新建的 form 技能,弹出窗口并锁定 input
            // if (form && messages.length === 0 && hisMessages.length === 0) {
            //     setInputLock({ locked: true, reason: '' })
            //     setFormShow(true)
            //     setShowWhenLocked(true)
            // }
        }

    }, [messages, hisMessages])
    useEffect(() => {
        if (!chatId) return
        // continueRef.current = false
        // setInputLock({ locked: false, reason: '' })
        // console.log('message chatid', messages, form, chatId);
        // setShowWhenLocked(false)

        currentChatIdRef.current = chatId
        // changeChatedRef.current = true
        // setFormShow(false)
        createWebSocket(chatId).then(() => {
            // 切换会话默认发送一条空消息(action, input)
            const wsMsg = onBeforSend('init_data', {})
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
        // 解除锁定状态下 form 按钮开放的状态
        // setShowWhenLocked(false)
        // 关闭引导词
        // setShowGuideQuestion(false)
        // 收起表单
        // formShow && setFormShow(false)
        // setFormShow(false)

        const value = inputRef.current.value
        if (value.trim() === '') return

        const event = new Event('input', { bubbles: true, cancelable: true });
        inputRef.current.value = ''
        inputRef.current.dispatchEvent(event); // 触发调节input高度
        // const contunue = continueRef.current ? 'continue' : ''
        // continueRef.current = false
        const wsMsg = onBeforSend('input', {
            nodeId: inputNodeIdRef.current,
            msg: value
        })
        // msg to store
        createSendMsg(value)
        // 锁定 input
        setInputLock({ locked: true, reason: '' })
        await createWebSocket(chatId)
        sendWsMsg(wsMsg)

        // 滚动聊天到底
        const messageDom = document.getElementById('message-panne')
        if (messageDom) {
            messageDom.scrollTop = messageDom.scrollHeight;
        }
    }

    const handleSendForm = async ([data, msg]) => {
        setInputForm(null)
        createSendMsg(msg)
        await createWebSocket(chatId)
        sendWsMsg({
            action: 'input',
            data: {
                node_id: inputNodeIdRef.current,
                data
            }
        })
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
    const createWebSocket = () => {
        // 单例
        if (wsRef.current) return Promise.resolve('ok');
        const isSecureProtocol = window.location.protocol === "https:";
        const webSocketProtocol = isSecureProtocol ? "wss" : "ws";

        return new Promise((res, rej) => {
            try {
                const ws = new WebSocket(`${webSocketProtocol}://${wsUrl}`)
                wsRef.current = ws
                // websocket linsen
                ws.onopen = () => {
                    console.log("WebSocket connection established!");
                    res('ok')
                };
                ws.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    console.log('result message data :>> ', data);
                    // const errorMsg = data.category === 'error' ? data.intermediate_steps : ''
                    // // 异常类型处理，提示
                    // if (errorMsg) return setInputLock({ locked: true, reason: errorMsg })
                    // // 拦截会话串台情况
                    // if (currentChatIdRef.current && currentChatIdRef.current !== data.chat_id) return
                    if (data.category === 'node_run') {
                        inputNodeIdRef.current = data.message.node_id
                    }
                    handleWsMessage(data)
                    // // 群聊@自己时，开启input
                    // if (['end', 'end_cover'].includes(data.type) && data.receiver?.is_self) {
                    //     setInputLock({ locked: false, reason: '' })
                    //     setStop({ show: false, disable: false })
                    //     setAutogenStop(true)
                    //     continueRef.current = true
                    // }
                    // if ('close' === data.type) {
                    //     setAutogenStop(false)
                    // }
                }
                ws.onclose = (event) => {
                    console.log('error event :>> ', event);
                    // wsRef.current = null
                    // console.error('链接手动断开 event :>> ', event);
                    // setStop({ show: false, disable: false })

                    // if ([1005, 1008, 1009].includes(event.code)) {
                    //     console.warn('即将废弃 :>> ');
                    //     setInputLock({ locked: true, reason: event.reason })
                    // } else {
                    //     if (event.reason) {
                    //         toast({
                    //             title: t('prompt'),
                    //             variant: 'error',
                    //             description: event.reason
                    //         });
                    //     }
                    //     setInputLock({ locked: false, reason: '' })
                    // }
                };
                ws.onerror = (ev) => {
                    wsRef.current = null
                    // setStop({ show: false, disable: false })
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
                };
            } catch (err) {
                console.error('创建链接异常', err);
                rej(err)
            }
        })
    }

    // 接受 ws 消息
    const handleWsMessage = (data) => {
        if (data.category === 'error') return toast({
            variant: 'error',
            description: data.message
        });
        if (data.category === 'node_run') {
            insetNodeRun(data)
            return sendNodeLogEvent(data)
        }
        if (data.category === 'user_input') {
            inputNodeIdRef.current = data.message.node_id
            // 待用户输入
            const form = onBeforSend('getInputForm', {
                nodeId: data.message.node_id,
                msg: ''
            })
            form ? setInputForm(form) : setInputLock({ locked: false, reason: '' })
            return
        } else if (data.category === 'guide_question') {
            return questionsRef.current.updateQuestions(data.message.filter(q => q))
        }
        if (data.type === 'close') {
            return insetSeparator('本轮会话已结束')
        } else if (data.type === 'over') {
            createWsMsg(data)
        } else if (data.type === 'stream') {
            streamWsMsg(data)
        }
        //  else if (data.type === 'stream') {
        //     updateCurrentMessage(data)
        // } else if (data.type === 'end') {
        //     updateCurrentMessage(data)
        // }

        // if (Array.isArray(data) && data.length) return
        // if (data.type === 'start') {
        //     msgClosedRef.current = false
        //     // 非continue时，展示stop按钮
        //     !continueRef.current && setStop({ show: true, disable: false })
        //     createWsMsg(data)
        // } else if (data.type === 'stream') {
        //     //@ts-ignore
        //     updateCurrentMessage({
        //         chat_id: data.chat_id,
        //         message: data.message,
        //         thought: data.intermediate_steps
        //     })
        // } else if (['end', 'end_cover'].includes(data.type)) {
        //     if (msgClosedRef.current && !['tool', 'flow', 'knowledge'].includes(data.category)) {
        //         // 无未闭合的消息，先创建（补一条start）  工具类除外
        //         console.log('重复end,新建消息 :>> ');
        //         createWsMsg(data)
        //     }
        //     updateCurrentMessage({
        //         ...data,
        //         end: true,
        //         thought: data.intermediate_steps || '',
        //         messageId: data.message_id,
        //         noAccess: false,
        //         liked: 0,
        //         update_time: formatDate(new Date(), 'yyyy-MM-ddTHH:mm:ss')
        //     }, data.type === 'end_cover')

        //     if (!msgClosedRef.current) msgClosedRef.current = true
        // } else if (data.type === "close") {
        //     setStop({ show: false, disable: false })
        //     setInputLock({ locked: false, reason: '' })
        // }
    }

    // 日志广播->nodes
    const sendNodeLogEvent = (data) => {
        const { node_id } = data.message
        const event = new CustomEvent('nodeLogEvent', {
            detail: {
                nodeId: node_id, action: data.type === 'start' ? 'loading' : 'success', data: []
            }
        })
        window.dispatchEvent(event)
    }

    // 触发发送消息事件（重试、表单）
    useEffect(() => {
        const handleCustomEvent = (e) => {
            if (!showWhenLocked && inputLock.locked) return console.error('弹窗已锁定，消息无法发送')
            const { send, message } = e.detail
            inputRef.current.value = message
            if (send) handleSendClick()
        }
        const handleOutPutEvent = async (e) => {
            const { nodeId, data } = e.detail
            await createWebSocket(chatId)
            sendWsMsg({
                action: 'input',
                data: {
                    [nodeId]: data
                }
            })
        }
        document.addEventListener('outputMsgEvent', handleOutPutEvent)
        document.addEventListener('userResendMsgEvent', handleCustomEvent)
        return () => {
            document.removeEventListener('outputMsgEvent', handleOutPutEvent)
            document.removeEventListener('userResendMsgEvent', handleCustomEvent)
        }
    }, [inputLock.locked, showWhenLocked])

    // 点击引导词
    const handleClickGuideWord = (message) => {
        if (inputLock.locked) return console.error('弹窗已锁定，消息无法发送')
        inputRef.current.value = message
        handleSendClick()
    }

    // auto input height
    const handleTextAreaHeight = (e) => {
        const textarea = e.target
        textarea.style.height = 'auto'
        textarea.style.height = textarea.scrollHeight + 'px'
        // setInputEmpty(textarea.value.trim() === '')
    }

    return <div className="absolute bottom-0 w-full pt-1 bg-[#fff] dark:bg-[#1B1B1B]">
        <div className={`relative ${clear && 'pl-9'}`}>
            {/* form */}
            {
                inputForm && <div className="relative">
                    <div className="absolute left-0 border bottom-2 bg-background-login px-4 py-2 rounded-md w-[50%] min-w-80 z-40">
                        <InputForm data={inputForm} onSubmit={handleSendForm} />
                    </div>
                </div>
            }
            {/* 引导问题 */}
            <GuideQuestions
                ref={questionsRef}
                locked={inputLock.locked}
                onClick={handleClickGuideWord}
            />
            {/* clear */}
            <div className="flex absolute left-0 top-4 z-10">
                {
                    clear && <div
                        className={`w-6 h-6 rounded-sm hover:bg-gray-200 cursor-pointer flex justify-center items-center `}
                        onClick={() => {
                            if (!stop.show) return
                            destory()
                            insetSeparator('本轮会话已结束')
                            sendWsMsg({ "action": "stop" });
                        }}
                    ><ClearIcon className={`${!showWhenLocked && inputLock.locked ? 'text-muted-foreground' : 'text-foreground'} dark:text-slate-50 dark:hover:bg-[#282828] hover:text-red-600`} ></ClearIcon></div>
                }
            </div>
            {/* form switch */}
            <div className="flex absolute left-3 top-4 z-10">
                {
                    form && <div
                        className={`w-6 h-6 rounded-sm hover:bg-gray-200 cursor-pointer flex justify-center items-center `}
                        onClick={() => (showWhenLocked || !inputLock.locked) && setFormShow(!formShow)}
                    ><FormIcon className={!showWhenLocked && inputLock.locked ? 'text-muted-foreground' : 'text-foreground'}></FormIcon></div>
                }
            </div>
            {/* send */}
            <div className="flex gap-2 absolute right-3 top-4 z-10">
                {stop.show ?
                    <div
                        onClick={() => {
                            if (stop.disable) return
                            setStop({ show: true, disable: true });
                            insetSeparator('本轮会话已结束')
                            sendWsMsg({ "action": "stop" });
                        }}
                        className={`w-6 h-6 bg-foreground rounded-full flex justify-center items-center cursor-pointer ${stop.disable && 'bg-muted-foreground text-muted-foreground'}`}>
                        <span className="w-2 h-2.5 border-x-2 border-border"></span>
                    </div>
                    : <div
                        id="bs-send-btn"
                        className="w-6 h-6 rounded-sm hover:bg-gray-200 dark:hover:bg-gray-950 cursor-pointer flex justify-center items-center"
                        onClick={() => { !inputLock.locked && handleSendClick() }}>
                        <SendIcon className={`${inputLock.locked ? 'text-muted-foreground' : 'text-foreground'}`} />
                    </div>
                }
            </div>
            {/* stop autogen等待输入时专用*/}
            <div className="absolute w-full flex justify-center bottom-32">
                {stop.show && <Button className="rounded-full" variant="outline" onClick={() => {
                    if (stop.disable) return
                    setStop({ show: true, disable: true });
                    setAutogenStop(false)
                    insetSeparator('本轮会话已结束')
                    sendWsMsg({ "action": "stop" });
                }}><CirclePause className="mr-2" />Stop</Button>}
            </div>
            {/* question */}
            <Textarea
                id="bs-send-input"
                ref={inputRef}
                rows={1}
                style={{ height: 56 }}
                disabled={inputLock.locked}
                onInput={handleTextAreaHeight}
                placeholder={inputLock.locked ? inputLock.reason : t('chat.inputPlaceholder')}
                className={"resize-none py-4 pr-10 text-md min-h-6 max-h-[200px] scrollbar-hide dark:bg-[#2A2B2E] text-gray-800" + (form && ' pl-10')}
                onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        !inputLock.locked && handleSendClick()
                    }
                }}
            ></Textarea>
        </div>
        <p className="text-center text-sm pt-2 pb-4 text-gray-400">{appConfig.dialogTips}</p>
    </div>
};
