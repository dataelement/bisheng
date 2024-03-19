import cloneDeep from "lodash-es/cloneDeep";
import { ClipboardList, FileInput, FileText, Send, StopCircle } from "lucide-react";
import { forwardRef, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ShadTooltip from "../../../components/ShadTooltipComponent";
import { Button } from "../../../components/ui/button";
import { alertContext } from "../../../contexts/alertContext";
import { TabsContext } from "../../../contexts/tabsContext";
import { getChatHistory, postBuildInit, postValidatePrompt } from "../../../controllers/API";
import { Variable } from "../../../controllers/API/flow";
import { sendAllProps } from "../../../types/api";
import { ChatMessageType } from "../../../types/chat";
import { FlowType, NodeType } from "../../../types/flow";
import { validateNode } from "../../../utils";
import { ChatMessage } from "./ChatMessage";
import ChatReportForm from "./ChatReportForm";
import ResouceModal from "./ResouceModal";
import ThumbsMessage from "./ThumbsMessage";
import { locationContext } from "../../../contexts/locationContext";

interface Iprops {
    chatId: string
    flow: FlowType
    queryString?: string
    version?: string
}

export default forwardRef(function ChatPanne({ chatId, flow, queryString, version = 'v1' }: Iprops) {
    const { t } = useTranslation()
    const { tabsState } = useContext(TabsContext);

    const { isRoom, isForm, isReport, checkPrompt } = useFlowState(flow)

    // build
    const build = useBuild(flow, chatId)
    // 消息列表
    const { messages, messagesRef, loadHistory, setChatHistory, changeHistoryByScroll } = useMessages(chatId, flow)
    // ws通信
    const { stop, connectWS, begin: chating, checkReLinkWs, sendAll } = useWebsocket(chatId, flow, setChatHistory, queryString, version)
    // 停止状态
    const [isStop, setIsStop] = useState(true)
    // 输入框状态
    const { inputState, inputEmpty, inputDisabled, inputRef,
        formShow, setFormShow,
        setInputState, setInputEmpty, handleTextAreaHeight } = useInputState({ flow, chatId, chating, messages, isForm, isReport })

    const { appConfig } = useContext(locationContext)

    // 开始构建&切换初始化会话
    const initChat = async () => {
        await checkPrompt(flow)
        await build()
        const historyData = await loadHistory()
        await connectWS({ setInputState, setIsStop, changeHistoryByScroll })
        setInputState({ lock: false, errorMsg: '' });
        // 第一条消息，用来初始化会话
        sendAll({
            chatHistory: messages,
            name: flow.name,
            description: flow.description,
            inputs: {},
            flow_id: flow.id,
            chat_id: chatId
        })

        changeHistoryByScroll.current = false
        // 自动聚焦
        if (inputRef.current) inputRef.current.value = ''
        setTimeout(() => {
            inputRef.current?.focus()
        }, 500);

        const isNewChat = historyData.length === 0 || historyData[0].id === 9999
        setFormShow(isNewChat && isForm)
    }
    useEffect(() => {
        initChat()
    }, [flow])

    // sendmsg user name
    const sendUserName = useMemo(() => {
        const node = flow.data.nodes.find(el => el.data.type === 'AutoGenUser')
        return node?.data.node.template['name'].value || ''
    }, [flow])

    const handleSend = async () => {
        const msg = inputRef.current?.value
        setTimeout(() => {
            if (inputRef.current) {
                inputRef.current.value = ''
                inputRef.current.style.height = 'auto'
            }
            setInputEmpty(true)
        }, 100);

        if (msg.trim() === '') return

        setInputState({ lock: true, errorMsg: '' });
        let inputs = tabsState[flow.id].formKeysData.input_keys;
        const input = inputs.find((el: any) => !el.type)
        const inputKey = input ? Object.keys(input)[0] : '';
        setChatHistory((old) => {
            let newChat = cloneDeep(old);
            newChat.push({
                isSend: true,
                message: { ...input, [inputKey]: msg },
                chatKey: inputKey,
                thought: '',
                category: '',
                files: [],
                end: false,
                user_name: ""
            })
            return newChat
        });

        await checkReLinkWs(async () => {
            // await build()
            await connectWS({ setInputState, setIsStop, changeHistoryByScroll })
        })

        const chatInfo = {
            chat_id: chatId,
            flow_id: flow.id,
            inputs: { ...input, [inputKey]: msg }
        }
        // @ts-ignore
        isRoom && chating ? sendAll({ action: "continue", ...chatInfo })
            : sendAll({
                chatHistory: messages,
                name: flow.name,
                description: flow.description,
                ...chatInfo
            });
    }


    // 报表请求
    const sendReport = (items: Variable[], str) => {
        let inputs = tabsState[flow.id].formKeysData.input_keys;
        const input = inputs.find((el: any) => !el.type)
        const inputKey = input ? Object.keys(input)[0] : '';
        setChatHistory((old) => {
            let newChat = cloneDeep(old);
            newChat.push({
                isSend: true,
                message: { ...input, [inputKey]: str },
                chatKey: inputKey,
                thought: '',
                category: '',
                files: [],
                end: false,
                user_name: ""
            })
            return newChat
        });

        const data = items.map(item => ({
            id: item.nodeId,
            name: item.name,
            file_path: item.type === 'file' ? item.value : '',
            value: item.type === 'file' ? '' : item.value
        }))

        setIsStop(false)
        setFormShow(false)

        sendAll({
            inputs: {
                ...input,
                [inputKey]: str,
                data
            },
            chatHistory: messages,
            name: flow.name,
            description: flow.description,
            chat_id: chatId,
            flow_id: flow.id,
        });
    }

    // 溯源
    const [souce, setSouce] = useState<ChatMessageType>(null)

    const thumbRef = useRef(null)

    return <div className="h-screen overflow-hidden relative">
        <div className="absolute px-2 py-2 bg-[#fff] z-10 dark:bg-gray-950 text-sm text-gray-400 font-bold">{flow.name}</div>
        <div className="chata mt-14" style={{ height: 'calc(100vh - 5rem)' }}>
            {/* 会话记录 */}
            <div ref={messagesRef} className={`chat-panne h-full overflow-y-scroll no-scrollbar px-4 ${isRoom || isReport ? 'pb-40' : 'pb-24'}`}>
                {
                    messages.map((c, i) => <ChatMessage
                        key={c.id || i}
                        userName={sendUserName}
                        chat={c}
                        disabledReSend={inputDisabled}
                        showSearch={!!appConfig.dialogQuickSearch}
                        onSource={() => setSouce(c)}
                        onDislike={(chatId) => { thumbRef.current?.openModal(chatId) }}
                        onReSend={(msg) => {
                            inputRef.current.value = msg
                            handleSend()
                        }}
                        onEdit={(msg) => { inputRef.current.value = msg; setInputEmpty(!msg) }}
                        onSearch={(msg) => window.open(appConfig.dialogQuickSearch + encodeURIComponent(msg))}
                    ></ChatMessage>)
                }
            </div>
            {/* 输入框 */}
            <div className="absolute w-full bottom-0 bg-gradient-to-t from-[#fff] to-[rgba(255,255,255,0.8)] px-8 dark:bg-gradient-to-t dark:from-[#000] dark:to-[rgba(0,0,0,0.8)]">
                <div className={`w-full text-area-box border border-gray-600 rounded-lg mt-6 mb-2 overflow-hidden pr-2 py-2 relative 
                  ${inputDisabled && 'bg-gray-200 dark:bg-gray-600'}`}>
                    <textarea id='input'
                        ref={inputRef}
                        disabled={inputDisabled} style={{ height: 36 }} rows={1}
                        className={`w-full resize-none border-none bg-transparent outline-none px-4 pt-1 text-xl max-h-[200px]`}
                        placeholder={t('chat.inputPlaceholder')}
                        onInput={handleTextAreaHeight}
                        onKeyDown={(event) => {
                            if (event.key === "Enter" && !event.shiftKey) handleSend()
                        }}></textarea>
                    <div className="absolute right-6 bottom-4 flex gap-2">
                        {
                            isForm && <ShadTooltip content={t('chat.forms')}>
                                <button disabled={chating} className=" disabled:text-gray-400" onClick={() => setFormShow(!formShow)}><ClipboardList /></button>
                            </ShadTooltip>
                        }
                        <ShadTooltip content={t('chat.sendTooltip')}>
                            <button disabled={inputEmpty || inputDisabled || chating} className=" disabled:text-gray-400" onClick={handleSend}><Send /></button>
                        </ShadTooltip>
                    </div>
                    {inputState.errorMsg && <div className="bg-gray-200 absolute top-0 left-0 w-full h-full text-center text-gray-400 align-middle pt-4">{inputState.errorMsg}</div>}
                </div>
                <p className="mb-2 text-center text-gray-400 text-sm">{appConfig.dialogTips}</p>
            </div>
        </div>
        {(isRoom || isReport) && <div className=" absolute w-full flex justify-center bottom-32 pointer-events-none">
            <Button className="rounded-full pointer-events-auto" variant="outline" disabled={isStop} onClick={() => { setIsStop(true); stop(); }}><StopCircle className="mr-2" />Stop</Button>
        </div>}
        {/* 源文件类型 */}
        <ResouceModal chatId={chatId} open={!!souce} data={souce} setOpen={() => setSouce(null)}></ResouceModal>
        {/* 表单 */}
        {isForm && formShow && <ChatReportForm flow={flow} onStart={sendReport} />}
        {/* 踩 反馈 */}
        <ThumbsMessage ref={thumbRef}></ThumbsMessage>
    </div>
});
/**
 * 输入框状态
 * 分析 flow状态
 * return 该技能含有表单、有报表、群聊
 * @returns 
 */
const useInputState = ({ flow, chatId, chating, messages, isForm, isReport }) => {
    const { tabsState } = useContext(TabsContext);

    const [inputState, setInputState] = useState({
        lock: false,
        errorMsg: ''
    })
    // 输入问答
    const inputRef = useRef(null)
    useEffect(() => {
        !chating && setTimeout(() => {
            // 对话结束自动聚焦
            inputRef.current?.focus()
        }, 1000);
    }, [chating])
    // input 滚动
    const [inputEmpty, setInputEmpty] = useState(true)
    useEffect(() => {
        setInputEmpty(true)
        if (inputRef.current) inputRef.current.value = ''
    }, [chatId])

    // 获取上传file input
    const fileInputs = useMemo(() => {
        return tabsState[flow.id]?.formKeysData?.input_keys?.filter((input: any) => input.type === 'file')
    }, [tabsState, flow])

    const handleTextAreaHeight = (e) => {
        const textarea = e.target
        textarea.style.height = 'auto'
        textarea.style.height = textarea.scrollHeight + 'px'
        setInputEmpty(textarea.value.trim() === '')
    }
    // input disabled
    const inputDisabled = useMemo(() => {
        return inputState.lock
            // 表单 && 没回话或只有一个引导词
            || (isForm && (messages.length === 0 || (messages.length === 1 && messages[0].id === 9999)))
            || isReport
    }, [inputState, fileInputs, isReport])

    // 表单收起
    const [formShow, setFormShow] = useState(true)
    return {
        inputState, inputEmpty, inputDisabled, inputRef,
        formShow, setFormShow,
        setInputState, setInputEmpty, handleTextAreaHeight
    }
}

/**
 * flow state
 * 分析 flow状态
 * return 该技能含有表单、有报表、群聊
 * @returns 
 */
const useFlowState = (flow: FlowType) => {
    const flowSate = useMemo(() => {
        // 是否群聊
        const isRoom = !!flow.data?.nodes.find(node => node.data.type === "AutoGenChain")
        // 是否展示表单
        const isForm = !!flow.data?.nodes.find(node => ["VariableNode", "InputFileNode"].includes(node.data.type))
        // 是否报表
        const isReport = !!flow.data?.nodes.find(node => "Report" === node.data.type)
        return { isRoom, isForm, isReport }
    }, [flow])

    // propmt类型补充自定义字段
    const checkPrompt = async (_flow) => {
        const params = _flow.data.nodes.map(node => {
            const temps = []
            const temp = node.data.node.template
            Object.keys(temp).map(key => {
                const { type, value } = temp[key]
                if (type === 'prompt' && !!value) !temps.length && temps.push({ name: key, template: value, data: node.data })
            })
            return temps
        }).flat()

        const promises = params.map(param => {
            return postValidatePrompt(param.name, param.template, param.data.node).then(res => {
                if (res) param.data.node = res.frontend_node
            })
        })
        return Promise.all(promises)
    }

    return { ...flowSate, checkPrompt }
}

/**
 * 消息列表模块
 * 翻页、追加、历史
 * @returns 
 */
const useMessages = (chatId, flow) => {
    const [chatHistory, setChatHistory] = useState<ChatMessageType[]>([]);
    const lastIdRef = useRef(0)
    // 控制开启自动随消息滚动（临时方案）
    const changeHistoryByScroll = useRef(false)

    const loadIdRef = useRef('') // 记录最后一个加载的 chatId
    // 获取聊天记录
    const loadHistory = async (lastId?: number) => {
        loadIdRef.current = chatId

        const res = await getChatHistory(flow.id, chatId, lastId ? 10 : 30, lastId)
        const hisData = res.map(item => {
            // let count = 0
            let { message, files, is_bot, intermediate_steps, ...other } = item
            try {
                message = message && message[0] === '{' ? JSON.parse(message.replace(/([\t\n"])/g, '\\$1').replace(/'/g, '"')) : message || ''
            } catch (e) {
                // 未考虑的情况暂不处理
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
        lastIdRef.current = hisData[hisData.length - 1]?.id || lastIdRef.current || 0 // 记录最后一个id

        let historyData = []
        if (lastId) {
            historyData = [...hisData.reverse(), ...chatHistory]
        } else if (loadIdRef.current === chatId) { // 保证同一会话
            historyData = !hisData.length && flow.guide_word ? [{
                "category": "system",
                "chat_id": chatId,
                "end": true,
                "create_time": "",
                "extra": "{}",
                "files": [],
                "flow_id": flow.id,
                "id": 9999,
                "thought": flow.guide_word,
                "is_bot": true,
                "liked": 0,
                "message": '',
                "receiver": null,
                "remark": null,
                "sender": "",
                "solved": 0,
                isSend: false,
                "source": 0,
                "type": "end",
                "update_time": "",
                noAccess: true,
                "user_id": 0
            }] : hisData.reverse()
        }

        setChatHistory(historyData)
        return historyData
    }

    const loadLock = useRef(false)
    const currentIdRef = useRef(0)
    const loadNextPage = async () => {
        if (loadLock.current) return
        if (currentIdRef.current === lastIdRef.current) return // 最后一个相同表示聊天记录已到顶
        loadLock.current = true
        currentIdRef.current = lastIdRef.current
        changeHistoryByScroll.current = true
        await loadHistory(currentIdRef.current)
        loadLock.current = false
        // 滚动 hack  TODO 滚动翻页设计
        setTimeout(() => {
            changeHistoryByScroll.current = false
        }, 500);
    }

    // 消息滚动
    const messagesRef = useRef(null);
    useEffect(() => {
        if (messagesRef.current && !changeHistoryByScroll.current) { // 滚动加载不触发
            messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
        }
    }, [chatHistory, changeHistoryByScroll]);

    // 消息滚动加载
    useEffect(() => {
        function handleScroll() {
            if (messagesRef.current.scrollTop <= 30) {
                loadNextPage()
            }
        }

        messagesRef.current?.addEventListener('scroll', handleScroll);
        return () => messagesRef.current?.removeEventListener('scroll', handleScroll)
    }, [messagesRef.current, chatHistory, chatId]);

    return {
        messages: chatHistory, messagesRef, loadHistory, setChatHistory, changeHistoryByScroll
    }
}

/**
 * websocket 通信
 * 建立连接、重连、断开、接收、发送
 * @returns 
 */
const useWebsocket = (chatId, flow, setChatHistory, queryString, version) => {
    const ws = useRef<WebSocket | null>(null);
    // 接收ws状态
    const [begin, setBegin] = useState(false)
    const { setErrorData } = useContext(alertContext);
    const { t } = useTranslation()

    const { appConfig } = useContext(locationContext)

    const chatIdRef = useRef(chatId);
    useEffect(() => {
        chatIdRef.current = chatId;
    }, [chatId])

    function heartbeat() {
        if (!ws.current) return;
        if (ws.current.readyState !== 1) return;
        ws.current.send("heartbeat");
        setTimeout(heartbeat, 30000);
    }

    function getWebSocketUrl(flowId, isDevelopment = false) {
        const token = localStorage.getItem("ws_token") || '';

        const isSecureProtocol = window.location.protocol === "https:";
        const webSocketProtocol = isSecureProtocol ? "wss" : "ws";
        const host = appConfig.websocketHost || window.location.host // isDevelopment ? "localhost:7860" : window.location.host;
        const chatEndpoint = version === 'v1' ? `/api/v1/chat/${flowId}?type=L1&chat_id=${chatId}&t=${token}`
            : `/api/v2/chat/ws/${flowId}?type=L1&chat_id=${chatId}${queryString}&t=${token}`

        return `${webSocketProtocol}://${host}${chatEndpoint}`;
    }

    const newChatStart = useRef(false) // 处理当前会话上下文丢失，阻止上一次打字机效果
    // 自动重连次数
    const tryReLinkCount = useRef(0)
    const reConnect = (params) => {
        if (tryReLinkCount.current <= 3) {
            connectWS(params)
            tryReLinkCount.current++
        } else {
            console.warn('超过最大重试次数 :>> ');
        }
    }
    useEffect(() => {
        tryReLinkCount.current = 0
        newChatStart.current = true
    }, [chatId])

    function connectWS(params) {
        const { setInputState, setIsStop, changeHistoryByScroll } = params
        if (ws.current) return Promise.resolve('ok');

        // 连接断开重链接
        return new Promise((res, rej) => {
            try {
                const urlWs = getWebSocketUrl(
                    flow.id,
                    process.env.NODE_ENV === "development"
                );
                const newWs = new WebSocket(urlWs);
                newWs.onopen = () => {
                    console.log("WebSocket connection established!");
                    res('ok')
                    // heartbeat()
                };
                newWs.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    if (data.chat_id !== chatIdRef.current) return
                    console.log('newChatStart.current :>> ', newChatStart.current);

                    const errorMsg = data.category === 'error' ? data.intermediate_steps : ''

                    if (newChatStart.current) {
                        if (data.type === 'close') {
                            newChatStart.current = false
                            return setInputState({ lock: false, errorMsg })
                        } else {
                            return setInputState({ lock: true, errorMsg })
                        }
                    }
                    // 异常类型处理，提示
                    if (errorMsg) return setInputState({ lock: true, errorMsg })

                    handleWsMessage({ data, setIsStop, setInputState, changeHistoryByScroll });
                    // get chat history
                    // 群聊@自己时，开启input
                    if (data.type === 'end' && data.receiver?.is_self) {
                        setInputState({ lock: false, errorMsg: '' })
                    }
                };
                newWs.onclose = (event) => {
                    ws.current = null

                    handleOnClose({ event, setIsStop, setInputState });
                    // reConnect(params)
                };
                newWs.onerror = (ev) => {
                    ws.current = null

                    console.error('链接异常error', ev);
                    setIsStop(true)

                    setErrorData({
                        title: `${t('chat.networkError')}:`,
                        list: [
                            t('chat.networkErrorList1'),
                            t('chat.networkErrorList2'),
                            t('chat.networkErrorList3')
                        ],
                    });
                    reConnect(params)
                };
                ws.current = newWs;
                console.log('newWs :>> ', newWs);
            } catch (error) {
                console.error('创建链接异常', error);
                rej(error)
            }
        })
    }

    var isStream = false;
    function handleWsMessage({ data, setIsStop, setInputState, changeHistoryByScroll }) {
        if (Array.isArray(data) && data.length) return
        if (data.type === "begin") {
            setBegin(true)
            setIsStop(false)
            changeHistoryByScroll.current = false
        }
        if (data.type === "close") {
            setBegin(false)
            setIsStop(true)
            setInputState({ lock: false, errorMsg: '' });
            changeHistoryByScroll.current = true
        }
        if (data.type === "start") {
            setChatHistory((old) => {
                let newChat = cloneDeep(old);
                newChat.push({
                    isSend: false,
                    message: '',
                    chatKey: '',
                    thought: data.intermediate_steps || '',
                    category: data.category || '',
                    files: [],
                    end: false
                })
                return newChat
            });
            isStream = true;
        }
        if (data.type === "stream" && isStream) {
            updateLastMessage({ str: data.message, thought: data.intermediate_steps });
        }
        if (data.type === "end") {
            updateLastMessage({
                ...data,
                str: data.message,
                files: data.files || null,
                end: true,
                thought: data.intermediate_steps || '',
                cate: data.category || '',
                messageId: data.message_id,
                noAccess: false,
                liked: 0
            });

            isStream = false;
        }
    }

    function updateLastMessage({ str, thought = '', end = false, files = [], cate = '', messageId = 0, source = false, noAccess = false, ...data }: {
        str: string;
        messageId?: number
        thought?: string;
        cate?: string;
        end?: boolean;
        files?: Array<any>;
        source?: boolean
        noAccess?: boolean
    }) {
        setChatHistory((old) => {
            const newChats = [...old]
            // console.log('newchats :>> ', newChats);
            let chatsLen = newChats.length
            const prevChat = newChats[chatsLen - 2]
            // hack 过滤重复最后消息
            if (end
                && str
                && chatsLen > 1
                && str === prevChat.message
                // && data.sender === prevChat.sender
                && !prevChat.thought) {
                newChats.splice(chatsLen - 2, 1) // 删上一条
                chatsLen = newChats.length
            }
            // 更新
            const lastChat = newChats[chatsLen - 1]
            const newLastChat = {
                ...newChats[chatsLen - 1],
                ...data,
                id: messageId,
                message: lastChat.message + str,
                thought: lastChat.thought + (thought ? `${thought}\n` : ''),
                files,
                category: cate,
                source,
                noAccess,
                end
            }
            newChats[chatsLen - 1] = newLastChat
            // start - end 之间没有内容删除load
            if (end && !(newLastChat.files.length || newLastChat.thought || newLastChat.message)) {
                newChats.pop()
            }
            return newChats;
        });
    }

    // 发送ws
    async function sendAll(data: sendAllProps) {
        try {
            if (ws) {
                if (JSON.stringify(data.inputs) !== '{}') {
                    newChatStart.current = false
                }
                ws.current.send(JSON.stringify(data));
            }
        } catch (error) {
            setErrorData({
                title: "There was an error sending the message",
                list: [error.message],
            });
        }
    }

    // 处理主动断开
    function handleOnClose({ event, setIsStop, setInputState }) {
        console.error('链接手动断开 event :>> ', event);
        setIsStop(true)
        setBegin(false)

        if ([1005, 1008].includes(event.code)) {
            console.warn('即将废弃 :>> ');
            setInputState({ lock: true, errorMsg: event.reason });
        } else {
            if (event.reason) {
                setErrorData({ title: event.reason });
                // setChatHistory((old) => {
                //     let newChat = cloneDeep(old);
                //     if (newChat.length) {
                //         newChat[newChat.length - 1].end = true;
                //     }
                //     newChat.push({ end: true, message: `${t('chat.connectionbreakTip')}${event.reason}`, isSend: false, chatKey: '', files: [] });
                //     return newChat
                // })
            }
            setInputState({ lock: false, errorMsg: '' });
        }
    }

    useEffect(() => {
        // destory
        return () => {
            // close prev connection
            if (ws.current) {
                switch (ws.current.readyState) {
                    case WebSocket.OPEN:
                        console.warn('前端主动关闭1')
                        ws.current.close()
                            ; break;
                    case WebSocket.CONNECTING:
                        ws.current.onopen = () => {
                            console.warn('前端主动关闭2')
                            ws.current.close()
                        };
                }
                ws.current = null
            }
        }
    }, [])

    // 检测并重连
    const checkReLinkWs = async (reConnect) => {
        if (ws.current) return true
        // 重连
        // 上一条加loading
        setChatHistory((old) => {
            let newChat = [...old];
            newChat[newChat.length - 1].category = 'loading';
            return newChat;
        });
        await reConnect()
        // 链接成功
        // 上一条去loading
        setChatHistory((old) => {
            let newChat = [...old];
            newChat[newChat.length - 1].category = '';
            return newChat;
        });
    }

    const handleStop = () => {
        try {
            if (ws) {
                ws.current.send(JSON.stringify({
                    "action": "stop"
                }));
            }
        } catch (error) {
            setErrorData({
                title: "There was an error stop the message",
                list: [error.message],
            });
        }
    }

    return { begin, stop: handleStop, checkReLinkWs, sendAll, connectWS }
}

/**
 * build flow
 * 校验每个节点，展示进度及结果；返回input_keys;end_of_stream断开链接
 * 主要校验节点并设置更新setTabsState的 formKeysData
 * @returns 
 */
const useBuild = (flow: FlowType, chatId: string) => {
    const { setErrorData } = useContext(alertContext);
    const { setTabsState } = useContext(TabsContext);
    const { t } = useTranslation()

    // SSE 服务端推送
    async function streamNodeData(flow: FlowType, chatId: string) {
        // Step 1: Make a POST request to send the flow data and receive a unique session ID
        const { flowId } = await postBuildInit(flow, chatId);
        // Step 2: Use the session ID to establish an SSE connection using EventSource
        let validationResults = [];
        let finished = false;
        const apiUrl = `/api/v1/build/stream/${flowId}?chat_id=${chatId}`;
        const eventSource = new EventSource(apiUrl);

        eventSource.onmessage = (event) => {
            // If the event is parseable, return
            if (!event.data) {
                return;
            }
            const parsedData = JSON.parse(event.data);
            // if the event is the end of the stream, close the connection
            if (parsedData.end_of_stream) {
                eventSource.close(); // 结束关闭链接
                return;
            } else if (parsedData.log) {
                // If the event is a log, log it
                // setSuccessData({ title: parsedData.log });
            } else if (parsedData.input_keys) {
                setTabsState((old) => {
                    return {
                        ...old,
                        [flowId]: {
                            ...old[flowId],
                            formKeysData: parsedData,
                        },
                    };
                });
            } else {
                // setProgress(parsedData.progress);
                validationResults.push(parsedData.valid);
            }
        };

        eventSource.onerror = (error: any) => {
            console.error("EventSource failed:", error);
            eventSource.close();
            if (error.data) {
                const parsedData = JSON.parse(error.data);
                setErrorData({ title: parsedData.error });
            }
        };
        // Step 3: Wait for the stream to finish
        while (!finished) {
            await new Promise((resolve) => setTimeout(resolve, 100));
            finished = validationResults.length === flow.data.nodes.length;
        }
        // Step 4: Return true if all nodes are valid, false otherwise
        return validationResults.every((result) => result);
    }

    // 延时器
    async function enforceMinimumLoadingTime(
        startTime: number,
        minimumLoadingTime: number
    ) {
        const elapsedTime = Date.now() - startTime;
        const remainingTime = minimumLoadingTime - elapsedTime;

        if (remainingTime > 0) {
            return new Promise((resolve) => setTimeout(resolve, remainingTime));
        }
    }

    async function handleBuild() {
        try {
            const errors = flow.data.nodes.flatMap((n: NodeType) => validateNode(n, flow.data.edges))
            if (errors.length > 0) {
                setErrorData({
                    title: t('chat.buildError'),
                    list: errors,
                });
                return;
            }

            const minimumLoadingTime = 200; // in milliseconds
            const startTime = Date.now();

            await streamNodeData(flow, chatId);
            await enforceMinimumLoadingTime(startTime, minimumLoadingTime); // 至少等200ms, 再继续(强制最小load时间)
        } catch (error) {
            console.error("Error:", error);
        } finally {
        }
    }

    return handleBuild
}