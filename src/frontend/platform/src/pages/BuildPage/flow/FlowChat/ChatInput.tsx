import { FormIcon } from "@/components/bs-icons/form";
import { SendIcon } from "@/components/bs-icons/send";
import { Button } from "@/components/bs-ui/button";
import { Textarea } from "@/components/bs-ui/input";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { locationContext } from "@/contexts/locationContext";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
// import GuideQuestions from "./GuideQuestions";
// import { useMessageStore } from "./messageStore";
import Tip from "@/components/bs-ui/tooltip/tip";
import { RefreshCw } from "lucide-react";
import useFlowStore from "../flowStore";
import ChatFiles from "./ChatFiles";
import GuideQuestions from "./GuideQuestions";
import { useMessageStore } from "./messageStore";

export const FileTypes = {
    IMAGE: ['.PNG', '.JPEG', '.JPG', '.BMP'],
    FILE: ['.PDF', '.TXT', '.MD', '.HTML', '.XLS', '.XLSX', '.DOC', '.DOCX', '.PPT', '.PPTX'],
}

export default function ChatInput({ autoRun, clear, form, wsUrl, onBeforSend, onLoad }) {
    const { toast } = useToast()
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)

    const [inputLock, setInputLock] = useState({ locked: true, reason: '' })
    const questionsRef = useRef(null)
    const inputNodeIdRef = useRef('') // 当前输入框节点id
    const messageIdRef = useRef('') // 当前输入框节点messageId
    const [accepts, setAccepts] = useState('*') // 接受文件类型

    const [showWhenLocked, setShowWhenLocked] = useState(false) // 强制开启表单按钮，不限制于input锁定

    const {
        messages,
        hisMessages,
        chatId,
        createSendMsg,
        createWsMsg,
        overWsMsg,
        inputForm,
        setInputForm,
        streamWsMsg,
        insetSeparator,
        destory,
        insetNodeRun,
        setShowGuideQuestion
    } = useMessageStore()
    console.log('ui messages :>> ', messages);

    const currentChatIdRef = useRef(null)
    const inputRef = useRef(null)
    const continueRef = useRef(false)
    // 停止状态
    const [stop, setStop] = useState({
        show: true,
        disable: false
    })
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
        if (!autoRun) return
        // continueRef.current = false
        // setInputLock({ locked: false, reason: '' })
        // console.log('message chatid', messages, form, chatId);
        // setShowWhenLocked(false)

        currentChatIdRef.current = chatId
        // changeChatedRef.current = true
        // setFormShow(false)
        createWebSocket().then(() => {
            // 切换会话默认发送一条空消息(action, input)
            const wsMsg = onBeforSend((messages.length === 0 && hisMessages.length === 0) || chatId.startsWith('test') ? 'init_data' : 'check_status', {})
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
        if (fileUploading) return
        // 解除锁定状态下 form 按钮开放的状态
        // setShowWhenLocked(false)
        // 关闭引导词
        // setShowGuideQuestion(false)
        // 收起表单
        // formShow && setFormShow(false)
        // setFormShow(false)
        const [filePath, fileNames] = getFileIds().reduce((acc, cur) => {
            acc[0].push(cur.path)
            acc[1].push(cur.name)
            return acc
        }, [[], []])
        // 文件拼接入消息
        const _value = inputRef.current.value
        if (_value.trim() === '' && filePath.length === 0) return
        const value = fileNames.length > 0 ? fileNames.join('\n') + '\n' + _value : _value;

        const event = new Event('input', { bubbles: true, cancelable: true });
        inputRef.current.value = ''
        inputRef.current.dispatchEvent(event); // 触发调节input高度
        // const contunue = continueRef.current ? 'continue' : ''
        // continueRef.current = false
        const wsMsg = onBeforSend('input', {
            nodeId: inputNodeIdRef.current,
            msg: value,
            files: filePath,
            category: "question",
            extra: '',
            message_id: messageIdRef.current,
            source: 0
        })
        // msg to store
        createSendMsg(value)
        // 锁定 input
        setInputLock({ locked: true, reason: '' })
        await createWebSocket()
        sendWsMsg(wsMsg)

        // 滚动聊天到底
        const messageDom = document.getElementById('message-panne')
        if (messageDom) {
            messageDom.scrollTop = messageDom.scrollHeight;
        }
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
    const reRunStateRef = useRef(false)
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
                    // 过滤一些不需要的数据
                    if ((data.category === 'end_cover' && data.type !== 'end_cover')) {
                        return
                    }

                    if (data.type === 'begin') {
                        setStop({ show: true, disable: false })
                    } else if (data.type === 'close' && data.category === 'processing') {
                        if (!reRunStateRef.current) {
                            // 重试时阻止关闭stop
                            setStop({ show: false, disable: false })
                        }
                        reRunStateRef.current = false
                    }

                    // const errorMsg = data.category === 'error' ? data.intermediate_steps : ''
                    // // 异常类型处理，提示
                    // if (errorMsg) return setInputLock({ locked: true, reason: errorMsg })
                    // // 拦截会话串台
                    if (data.chat_id && currentChatIdRef.current && currentChatIdRef.current !== data.chat_id) return
                    handleWsMessage(data);
                    ['begin', 'close'].includes(data.type) && onLoad()
                    // if ('close' === data.type) {
                    //     setAutogenStop(false)
                    // }
                }
                ws.onclose = (event) => {
                    console.log('error event :>> ', event);
                    // wsRef.current = null
                    // console.error('链接手动断开 event :>> ', event);
                    // setStop({ show: false, disable: false })

                    if ([1005, 1008, 1009].includes(event.code)) {
                        setInputLock({ locked: true, reason: event.reason })
                    } else {
                        if (event.reason) {
                            toast({
                                title: t('prompt'),
                                variant: 'error',
                                description: event.reason
                            });
                        }
                        setInputLock({ locked: true, reason: '' })
                    }
                    event.reason && addNotification({
                        type: 'error',
                        title: '运行异常',
                        description: event.reason
                    })
                };
                ws.onerror = (ev) => {
                    wsRef.current = null
                    // setStop({ show: false, disable: false })
                    console.error('链接异常error', ev);
                    // toast({
                    //     title: `${t('chat.networkError')}:`,
                    //     variant: 'error',
                    //     description: [
                    //         t('chat.networkErrorList1'),
                    //         t('chat.networkErrorList2'),
                    //         t('chat.networkErrorList3')
                    //     ]
                    // });
                    setInputLock({ locked: true, reason: '' })
                };
            } catch (err) {
                console.error('创建链接异常', err);
                rej(err)
            }
        })
    }

    const setRunCache = useFlowStore(state => state.setRunCache)
    const addNotification = useFlowStore((state) => state.addNotification);
    // 接受 ws 消息
    const handleWsMessage = (data) => {
        if (data.category === 'error') {
            const { code, message } = data.message
            setInputLock({ locked: true, reason: '' })

            // 记录
            const errorMsg = code == 500 ? message : t(`errors.${code}`, { type: message })
            addNotification({
                type: 'error',
                title: '运行异常',
                description: errorMsg
            })

            return toast({
                variant: 'error',
                description: errorMsg
            });
        } else if (data.category === 'node_run') {
            inputNodeIdRef.current = data.message.node_id
            // 缓存运行结果,用于[单节点运行]自动填写参数
            if (data.type === 'end' && data.message.input_data) {
                setRunCache(data.message.node_id
                    , data.message.input_data)
            }
            insetNodeRun(data)
            return sendNodeLogEvent(data)
        } else if (data.category === "guide_word") {
            data.message.msg = data.message.guide_word
        } else if (data.category === 'input') {
            const { node_id, input_schema } = data.message
            inputNodeIdRef.current = node_id
            messageIdRef.current = data.message_id
            // 限制文件类型
            if (input_schema.tab === 'dialog_input') {
                const schemaItem = input_schema.value?.find(el => el.key === 'dialog_file_accept')
                const fileAccept = schemaItem?.value
                if (fileAccept === 'image') {
                    setAccepts(FileTypes.IMAGE.join(','))
                } else if (fileAccept === 'file') {
                    setAccepts(FileTypes.FILE.join(','))
                } else {
                    setAccepts(FileTypes.IMAGE.join(',') + ',' + FileTypes.FILE.join(','))
                }
            }
            // 待用户输入
            input_schema.tab === 'form_input' ? setInputForm(input_schema) : setInputLock({ locked: false, reason: '' })
            return
        } else if (data.category === 'guide_question') {
            return questionsRef.current.updateQuestions(data.message.guide_question.filter(q => q))
        } else if (data.category === 'stream_msg') {
            streamWsMsg(data)
        } else if (data.category === 'end_cover' && data.type === 'end_cover') {
            setInputLock({ locked: true, reason: '' })
            sendWsMsg({ "action": "stop" });
            return overWsMsg(data)
            // return handleRestartClick()
        }

        if (data.type === 'close' && data.category === 'processing') {
            insetSeparator(t('chat.chatEndMessage'))
            setInputLock({ locked: true, reason: '' })
            // 重启会话按钮,接收close确认后端处理结束后重启会话
            if (restartCallBackRef.current[data.chat_id]) {
                restartCallBackRef.current[data.chat_id]()
                restartCallBackRef.current[data.chat_id] = null
            }
        } else if (data.type === 'over') {
            createWsMsg(data)
        }
    }

    // 日志广播->nodes
    const sendNodeLogEvent = (data) => {
        const { node_id } = data.message
        const isError = !!data.message.reason
        const event = new CustomEvent('nodeLogEvent', {
            detail: {
                nodeId: node_id,
                action: isError ? '' : data.type === 'start' ? 'loading' : 'success',
                data: isError ? { 'error': data.message.reason } : data.message.log_data // 缓存TODO
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
            const { nodeId, data, message } = e.detail
            const { flow_id, chat_id } = onBeforSend('flowInfo', {})
            await createWebSocket()
            sendWsMsg({
                action: 'input',
                flow_id,
                chat_id,
                data: {
                    [nodeId]: {
                        data,
                        message: JSON.stringify({
                            ...message.message,
                            input_msg: Object.values(data)[0],
                            hisValue: Object.values(data)[0]
                        }),
                        message_id: message.message_id
                    }
                }
            })
        }
        const handleSendForm = async (e) => {
            const { data, msg } = e.detail
            setInputForm(null)
            createSendMsg(msg)
            await createWebSocket()
            const { flow_id, chat_id } = onBeforSend('flowInfo', {})
            sendWsMsg({
                action: 'input',
                flow_id,
                chat_id,
                data: {
                    [inputNodeIdRef.current]: {
                        data,
                        message: msg,
                        message_id: messageIdRef.current,
                        category: 'question',
                        extra: '',
                        source: 0
                    }
                }
            })
        }
        document.addEventListener('inputFormEvent', handleSendForm)
        document.addEventListener('outputMsgEvent', handleOutPutEvent)
        document.addEventListener('userResendMsgEvent', handleCustomEvent)
        return () => {
            document.removeEventListener('inputFormEvent', handleSendForm)
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

    // stop click
    const handleStopClick = () => {
        if (stop.disable) return
        setStop({ show: true, disable: true });
        setInputLock({ locked: true, reason: '' })
        sendWsMsg({ "action": "stop" });
    }
    // restart
    const restartCallBackRef = useRef({})
    const [restarted, setRestarted] = useState(false)
    const handleRestartClick = () => {
        sendWsMsg({ "action": "stop" });
        setInputForm(null)
        setRestarted(true)
        const chatId = currentChatIdRef.current.startsWith('test') ? '' : currentChatIdRef.current
        restartCallBackRef.current[chatId] = () => {
            createWebSocket().then(() => {
                setRestarted(false)
                onBeforSend('refresh_flow', {}).then((data) => {
                    sendWsMsg(data)
                })
            })
        }
        // wsRef.current?.close()
        // wsRef.current = null
        // stop.show && insetSeparator(t('chat.chatEndMessage'))
        // setTimeout(() => {
        //     createWebSocket().then(() => {
        //         sendWsMsg(onBeforSend('init_data', {}))
        //     })
        // }, 300);
        if (stop.show) {
            reRunStateRef.current = true
        }
    }

    const placholder = useMemo(() => {
        // if (inputForm) {
        //     return '      点击刷新按钮可开启新对话'
        // }
        const reason = inputLock.reason || ' '
        return inputLock.locked ? reason : t('chat.inputPlaceholder')
    }, [inputForm, inputLock])

    // 文件上传状态
    const { fileUploading, getFileIds, loadingChange } = useFileLoading(inputLock.locked)

    return <div className="absolute bottom-0 w-full pt-1 bg-[#fff] dark:bg-[#1B1B1B]">
        <div className={`relative pr-4 ${clear && 'pl-9'}`}>
            {/* 引导问题 */}
            <GuideQuestions
                ref={questionsRef}
                locked={inputLock.locked}
                onClick={handleClickGuideWord}
            />
            {/* restart */}
            <div className="flex absolute left-0 top-3 z-10">
                <Tip side='top-right' content={"重新运行"}>
                    <Button className="rounded-full" disabled={restarted} variant="ghost" size="icon" onClick={handleRestartClick}><RefreshCw size={18} /></Button>
                </Tip>
            </div>
            {/* form switch */}
            <div className="flex absolute left-3 top-4 z-10">
                {
                    form && <div
                        className={`w-6 h-6 rounded-sm hover:bg-gray-200 cursor-pointer flex justify-center items-center `}
                    // onClick={() => (showWhenLocked || !inputLock.locked) && setFormShow(!formShow)}
                    ><FormIcon className={!showWhenLocked && inputLock.locked ? 'text-muted-foreground' : 'text-foreground'}></FormIcon></div>
                }
            </div>
            {/* 附件 */}
            {!inputLock.locked && <ChatFiles accepts={accepts} v={location.href.indexOf('/chat/flow/') === -1 ? 'v1' : 'v2'} onChange={loadingChange} />}
            {/* send */}
            <div className="flex gap-2 absolute right-7 top-4 z-10">
                <div
                    id="bs-send-btn"
                    className="w-6 h-6 rounded-sm hover:bg-gray-200 dark:hover:bg-gray-950 cursor-pointer flex justify-center items-center"
                    onClick={() => { !inputLock.locked && !fileUploading && handleSendClick() }}>
                    <SendIcon className={`${inputLock.locked || fileUploading ? 'text-muted-foreground' : 'text-foreground'}`} />
                </div>
            </div>
            {/* stop & 重置 */}
            <div className="absolute w-full flex justify-center bottom-16">
                {!stop.show && <Button
                    className="rounded-full bg-[#fff] dark:bg-[#1B1B1B]"
                    variant="outline"
                    disabled={restarted}
                    onClick={handleRestartClick}>
                    <RefreshCw className="mr-1" size={16} />
                    {t('chat.runNewWorkflow')}
                </Button>
                }
            </div>
            {/* question */}
            <Textarea
                id="bs-send-input"
                ref={inputRef}
                rows={1}
                style={{ height: 56 }}
                disabled={inputLock.locked}
                onInput={handleTextAreaHeight}
                placeholder={placholder}
                className={"resize-none py-4 pr-10 text-md min-h-6 max-h-[200px] scrollbar-hide dark:bg-[#131415] text-gray-800" + (form && ' pl-10')}
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



const useFileLoading = (locked) => {
    const [loading, setLoading] = useState(false);
    const filesRef = useRef([])
    useEffect(() => {
        if (locked) filesRef.current = []
    }, [locked])
    return {
        fileUploading: loading,
        getFileIds: () => filesRef.current,
        loadingChange(files: string[] | null) {
            if (files) {
                setLoading(false)
                filesRef.current = files
            } else {
                setLoading(true)
                filesRef.current = []
            }
        },
        clear() {
            setLoading(false)
            filesRef.current = []
        }
    }
}