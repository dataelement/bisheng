// @ts-strict-ignore
import { ConversationComposer } from '@bisheng/chat';
import { Button, notification } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";






import { useAudioStore } from "@/components/voiceFunction/audioPlayerStore";
import SpeechToTextComponent from "@/components/voiceFunction/speechToText";
import { locationContext } from "@/contexts/locationContext";
import { useWorkbenchRuntimeConfig } from "@/hooks/useWorkbenchRuntimeConfig";
import { formatDate } from "@/util/utils";

import { useContext,useEffect,useRef,useState } from "react";
import { useTranslation } from "react-i18next";
import { useVoiceDraft } from "@/hooks/useVoiceDraft";
import { isBlockingChatError,resolveChatErrorMessage } from "./chatErrorMessage";
import { useMessageStore } from "./messageStore";

export default function ChatInput({ clear, form, inputForm, wsUrl, onBeforSend, onClickClear }) {

    const eventTarget = useMessageStore(state => state.eventTarget)
    const { t } = useTranslation(['bs', 'shared'])
    const { appConfig } = useContext(locationContext)

    const [formShow, setFormShow] = useState(false)
    const [showWhenLocked, setShowWhenLocked] = useState(false) // 强制开启表单按钮，不限制于input锁定
    const [inputLock, setInputLock] = useState({ locked: false, reason: '' })
    const { data: linsightConfig } = useWorkbenchRuntimeConfig();

    const { isLoading: audioOpening } = useAudioStore()

    const { messages, hisMessages, chatId, createSendMsg, createWsMsg, updateCurrentMessage, closeDanglingRunLogs, destory, setShowGuideQuestion, setInputLocked } = useMessageStore()
    useEffect(() => { setInputLocked(inputLock.locked); }, [inputLock.locked, setInputLocked]);
    const currentChatIdRef = useRef(null)
    const inputRef = useRef<HTMLTextAreaElement>(null)
    const voice = useVoiceDraft(inputRef, '', (value) => {
        if (!inputRef.current) return
        inputRef.current.value = value
        inputRef.current.dispatchEvent(new Event('input', { bubbles: true }))
    })
    const continueRef = useRef(false)
    // 停止状态
    const [stop, setStop] = useState({
        show: false,
        disable: false
    })
    const [autogenStop, setAutogenStop] = useState(false)

    useEffect(() => {
        if (!chatId) return
        continueRef.current = false
        // console.log('message chatid', messages, form, chatId);

        if (form && messages.length === 0 && hisMessages.length === 0) {
            setInputLock({ locked: true, reason: '' })
            setFormShow(true)
            setShowWhenLocked(true)
        } else {
            setFormShow(false)
            setShowWhenLocked(false)
            setInputLock({ locked: false, reason: '' })
        }
        currentChatIdRef.current = chatId
        createWebSocket(chatId).then(() => {
            // 切换会话默认发送一条空消息
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
        if (voice.busy) return
        // 解除锁定状态下 form 按钮开放的状态
        setShowWhenLocked(false)
        // 关闭引导词
        setShowGuideQuestion(false)
        // 收起表单
        // formShow && setFormShow(false)
        setFormShow(false)

        const value = inputRef.current.value
        if (value.trim() === '') return

        const event = new Event('input', { bubbles: true, cancelable: true });
        inputRef.current.value = ''
        inputRef.current.dispatchEvent(event); // 触发调节input高度
        const contunue = continueRef.current ? 'continue' : ''
        continueRef.current = false
        const [wsMsg, inputKey] = onBeforSend(contunue, value)
        // msg to store
        createSendMsg(wsMsg.inputs, inputKey)
        // 锁定 input
        setInputLock({ locked: true, reason: '' })
        await createWebSocket(chatId)
        sendWsMsg(wsMsg)

        // 滚动聊天到底

    }

    const diffRef = useRef(0)
    const sendWsMsg = async (msg) => {
        try {
            diffRef.current = Date.now()
            // console.log('WebSocket send: ' + diffRef.current + ' 毫秒');

            wsRef.current.send(JSON.stringify(msg))
        } catch (error) {
            notification.open({ type: 'error', title: String('There was an error sending the message'), description: String(error.message ?? '') });
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
                    // 记录连接成功的时间

                    // 计算连接建立所需的时间

                    // console.log('WebSocket 连接建立时间: ' + connectionTime + ' 毫秒');
                    console.log("WebSocket connection established!");
                    res('ok')
                };
                ws.onmessage = (event) => {
                    // console.log(`WebSocket get: ${Date.now()} 毫秒；与send差值${Date.now() - diffRef.current}毫秒`);
                    const data = JSON.parse(event.data);

                    if (data.category === 'error') {
                        const errorMsg = resolveChatErrorMessage(data.message, t)
                        notification.open({ type: 'error', description: String(errorMsg ?? '') })
                        updateCurrentMessage({
                            type: 'end_cover',
                            category: 'tool',
                            message: "{}"
                        }, true)
                        setStop({ show: false, disable: false })
                        // A runtime failure (model auth, tool error) is retryable: keep the input
                        // usable instead of parking the raw error in its placeholder. Only a dead
                        // conversation (assistant deleted / offline) locks the input.
                        return setInputLock(isBlockingChatError(data.message)
                            ? { locked: true, reason: errorMsg }
                            : { locked: false, reason: '' })
                    }
                    // 拦截会话串台情况
                    if (currentChatIdRef.current && currentChatIdRef.current !== data.chat_id) return
                    handleWsMessage(data)
                    // 群聊@自己时，开启input
                    if (['end', 'end_cover'].includes(data.type) && data.receiver?.is_self) {
                        setInputLock({ locked: false, reason: '' })
                        setStop({ show: false, disable: false })
                        setAutogenStop(true)
                        continueRef.current = true
                    }
                    if ('close' === data.type) {
                        setAutogenStop(false)
                    }
                }
                ws.onclose = (event) => {
                    // wsRef.current = null
                    console.error('链接手动断开 event :>> ', event);
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
                    setStop({ show: false, disable: false })
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
                    // reConnect(params)
                };
            } catch (err) {
                console.error('创建链接异常', err);
                rej(err)
            }
        })
    }

    // 接受 ws 消息
    const msgClosedRef = useRef(true) // 消息闭合
    const handleWsMessage = (data) => {
        if (Array.isArray(data) && data.length) return
        if (data.type === 'start') {
            msgClosedRef.current = false
            // 非continue时，展示stop按钮
            !continueRef.current && setStop({ show: true, disable: false })
            createWsMsg(data)
        } else if (data.type === 'stream') {
            //@ts-ignore
            updateCurrentMessage({
                chat_id: data.chat_id,
                message: data.message,
                thought: data.intermediate_steps
            })
        } else if (['end', 'end_cover'].includes(data.type)) {
            if (msgClosedRef.current && !['tool', 'flow', 'knowledge'].includes(data.category)) {
                // 无未闭合的消息，先创建（补一条start）  工具类除外
                console.log('重复end,新建消息 :>> ');
                createWsMsg(data)
            }
            updateCurrentMessage({
                ...data,
                end: true,
                thought: data.intermediate_steps || '',
                messageId: data.message_id,
                noAccess: false,
                liked: 0,
                create_time: formatDate(new Date(), 'yyyy-MM-ddTHH:mm:ss')
            }, data.type === 'end_cover' && data.category === 'anwser')

            if (!msgClosedRef.current) msgClosedRef.current = true
        } else if (data.type === "close") {
            closeDanglingRunLogs()
            setStop({ show: false, disable: false })
            setInputLock((prev) => (prev.reason ? prev : { locked: false, reason: '' }))
        }
    }

    // 触发发送消息事件（重试、表单）
    useEffect(() => {
        const handleCustomEvent = (e) => {
            if (voice.busy) return
            if (!showWhenLocked && inputLock.locked) return console.error('弹窗已锁定，消息无法发送')
            const { send, message } = e.detail
            inputRef.current.value = message
            if (send) handleSendClick()
        }
        eventTarget.addEventListener('userResendMsgEvent', handleCustomEvent)
        return () => {
            eventTarget.removeEventListener('userResendMsgEvent', handleCustomEvent)
        }
    }, [inputLock.locked, showWhenLocked, voice.busy])

    return <div className="absolute bottom-0 w-full z-10">
        {formShow && <div className="relative"><div className="absolute left-0 border bottom-2 bg-background-login px-4 py-2 rounded-md w-[50%] min-w-80 z-40">{inputForm}</div></div>}
        <ConversationComposer inputRef={inputRef} canExecute inputDisabled={inputLock.locked} busy={audioOpening || voice.busy}
            showStop={stop.show} stopDisabled={stop.disable}
            labels={{ send: t('shared:app_chat.send'), stop: t('shared:app_chat.stop'), restart: t('chat.runNewWorkflow') }}
            placeholder={inputLock.locked ? inputLock.reason : t('chat.inputPlaceholder')} hint={appConfig.dialogTips}
            onSend={handleSendClick} onStop={() => { if (!stop.disable) { setStop({ show: true, disable: true }); sendWsMsg({ action: 'stop' }); } }}
            onInput={event => voice.handleEdit(event.currentTarget.value)} onCompositionStart={voice.compositionStart} onCompositionEnd={voice.compositionEnd}
            voice={linsightConfig?.asr_model?.id ? <SpeechToTextComponent inline key={chatId} {...voice.props} disabled={inputLock.locked}
                realtime={!!linsightConfig.asr_model.realtime} modelId={linsightConfig.asr_model.id} /> : undefined}
            leadingActions={<div className="flex absolute left-0 top-4 z-10">
                {clear && <Button size="small" variant="text" color="default" disabled={inputLock.locked} onClick={() => onClickClear?.()}><Outlined.Delete size={16} /></Button>}
                {form && <Button size="small" variant="text" color="default" disabled={!showWhenLocked && inputLock.locked} onClick={() => setFormShow(!formShow)}><Outlined.Upload size={16} /></Button>}
            </div>} />
        {autogenStop && <Button variant="outlined" color="default" onClick={() => { if (!stop.disable) { setStop({ show: true, disable: true }); setAutogenStop(false); sendWsMsg({ action: 'stop' }); } }}><Outlined.PlayerPause size={16} />{t('shared:app_chat.stop')}</Button>}
    </div>;
}
