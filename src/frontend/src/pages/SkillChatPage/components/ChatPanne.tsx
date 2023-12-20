import _ from "lodash";
import { Send, StopCircle } from "lucide-react";
import { forwardRef, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ShadTooltip from "../../../components/ShadTooltipComponent";
import { Button } from "../../../components/ui/button";
import { alertContext } from "../../../contexts/alertContext";
import { TabsContext } from "../../../contexts/tabsContext";
import { getChatHistory, postBuildInit, postValidatePrompt,chatResolved } from "../../../controllers/API";
import { Variable } from "../../../controllers/API/flow";
import { sendAllProps } from "../../../types/api";
import { ChatMessageType } from "../../../types/chat";
import { FlowType, NodeType } from "../../../types/flow";
import { validateNode } from "../../../utils";
import { ChatMessage } from "./ChatMessage";
import ChatReportForm from "./ChatReportForm";
import ResouceModal from "./ResouceModal";

interface Iprops {
    chatId: string
    flow: FlowType
    libId?: string
    version?: string
    onReload: (flow: FlowType) => void
}

export default forwardRef(function ChatPanne({ chatId, flow, libId, version = 'v1', onReload }: Iprops) {

    const { t } = useTranslation()
    const { tabsState } = useContext(TabsContext);

    const { isRoom, isForm, isReport, checkPrompt } = useFlowState(flow)

    // build
    const build = useBuild(flow, chatId)
    // 消息列表
    const { messages, messagesRef, loadHistory, setChatHistory, changeHistoryByScroll } = useMessages(chatId, flow)
    // ws通信
    const { stop, connectWS, closeWs, begin: chating, checkReLinkWs, sendAll } = useWebsocket(chatId, flow, setChatHistory, libId, version)
    // 停止状态
    const [isStop, setIsStop] = useState(true)
    // 输入框状态
    const { inputState, inputEmpty, inputDisabled, inputRef, setInputState, setInputEmpty, handleTextAreaHeight } = useInputState({ flow, chatId, chating, messages, isReport })

    // 开始构建&初始化会话
    const initChat = async () => {
        await checkPrompt(flow)
        await build()
        connectWS({ setInputState, setIsStop, changeHistoryByScroll })
        loadHistory()

        changeHistoryByScroll.current = false
        // 自动聚焦
        if (inputRef.current) inputRef.current.value = ''
        setTimeout(() => {
            inputRef.current?.focus()
        }, 500);
    }
    useEffect(() => {
        initChat()
        return () => {
            closeWs()
            setChatHistory([])
        }
    }, [])

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

        setInputState({ lock: true, errorCode: '' });
        let inputs = tabsState[flow.id].formKeysData.input_keys;
        const input = inputs.find((el: any) => !el.type)
        const inputKey = input ? Object.keys(input)[0] : '';
        setChatHistory((old) => {
            let newChat = _.cloneDeep(old);
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
            await build()
            await connectWS({ setInputState, setIsStop, changeHistoryByScroll })
        })

        // @ts-ignore
        isRoom && chating ? sendAll({ action: "continue", "inputs": { ...input, [inputKey]: msg } })
            : sendAll({
                ...flow.data,
                inputs: { ...input, [inputKey]: msg },
                chatHistory: messages,
                name: flow.name,
                description: flow.description
            });
    }


    // 报表请求
    const sendReport = (items: Variable[], str) => {
        let inputs = tabsState[flow.id].formKeysData.input_keys;
        const input = inputs.find((el: any) => !el.type)
        const inputKey = input ? Object.keys(input)[0] : '';
        setChatHistory((old) => {
            let newChat = _.cloneDeep(old);
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

        sendAll({
            ...flow.data,
            inputs: {
                ...input,
                [inputKey]: str,
                data
            },
            chatHistory: messages,
            name: flow.name,
            description: flow.description
        });
    }

    // 溯源
    const [souce, setSouce] = useState<ChatMessageType>(null)

    const helpful=useHelpful(messages,chatId,chating,inputState,onReload,setInputState)
    return <div className="h-screen overflow-hidden relative">
        <div className="absolute px-2 py-2 bg-[#fff] z-10 dark:bg-gray-950 text-sm text-gray-400 font-bold">{flow.name}</div>
        <div className="chata mt-14" style={{ height: 'calc(100vh - 5rem)' }}>
            <div ref={messagesRef} className={`chat-panne h-full overflow-y-scroll no-scrollbar px-4 pb-36`}>
                {
                    messages.map((c, i) => <ChatMessage key={c.id || i} userName={sendUserName} chat={c} onSource={() => setSouce(c)}></ChatMessage>)
                }
            </div>
            <div className="absolute w-full bottom-0 bg-gradient-to-t from-[#fff] to-[rgba(255,255,255,0.8)] px-8  pt-3 dark:bg-gradient-to-t dark:from-[#000] dark:to-[rgba(0,0,0,0.8)]">
                        {/* 有没有帮助 */}
                        {helpful}
                <div className={`w-full text-area-box border border-gray-600 rounded-lg mb-6 mt-3 overflow-hidden pr-2 py-2 relative 
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
                        <ShadTooltip content={t('chat.sendTooltip')}>
                            <button disabled={inputEmpty || inputDisabled} className=" disabled:text-gray-400" onClick={handleSend}><Send /></button>
                        </ShadTooltip>
                    </div>
                    {inputState.errorCode && <div className="bg-gray-200 absolute top-0 left-0 w-full h-full text-center text-gray-400 align-middle pt-4">{t(`status.${inputState.errorCode}`)}</div>}
                </div>
            </div>
        </div>
        {(isRoom || isReport) && <div className=" absolute w-full flex justify-center bottom-32">
            <Button className="rounded-full" variant="outline" disabled={isStop} onClick={() => { setIsStop(true); stop(); }}><StopCircle className="mr-2" />Stop</Button>
        </div>}

        {/* 源文件类型 */}
        <ResouceModal chatId={chatId} open={!!souce} data={souce} setOpen={() => setSouce(null)}></ResouceModal>
        {/* 表单 */}
        {isForm && !messages.length && <ChatReportForm flow={flow} onStart={sendReport} />}
    </div>
});
/**
 * 输入框状态
 * 分析 flow状态
 * return 该技能含有表单、有报表、群聊
 * @returns 
 */
const useInputState = ({ flow, chatId, chating, messages, isReport }) => {
    const { tabsState } = useContext(TabsContext);

    const [inputState, setInputState] = useState({
        lock: false,
        errorCode: ''
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
        return inputState.lock || (fileInputs?.length && messages.length === 0) || isReport
    }, [inputState, fileInputs, isReport])

    return {
        inputState, inputEmpty, inputDisabled, inputRef, setInputState, setInputEmpty, handleTextAreaHeight
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
                if (res.data) param.data.node = res.data.frontend_node
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

    // 获取聊天记录
    const loadHistory = async (lastId?: number) => {
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
        lastIdRef.current = hisData[hisData.length - 1]?.id || lastIdRef.current // 记录最后一个id
        setChatHistory((history) => [...hisData.reverse(), ...history])
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
    }, [messagesRef.current]);

    return {
        messages: chatHistory, messagesRef, loadHistory, setChatHistory, changeHistoryByScroll
    }
}

/**
 * websocket 通信
 * 建立连接、重连、断开、接收、发送
 * @returns 
 */
const useWebsocket = (chatId, flow, setChatHistory, libId, version) => {
    const ws = useRef<WebSocket | null>(null);
    // 接收ws状态
    const [begin, setBegin] = useState(false)
    const { setErrorData } = useContext(alertContext);
    const { t } = useTranslation()

    function heartbeat() {
        if (!ws.current) return;
        if (ws.current.readyState !== 1) return;
        ws.current.send("heartbeat");
        setTimeout(heartbeat, 30000);
    }

    function getWebSocketUrl(flowId, isDevelopment = false) {
        const isSecureProtocol = window.location.protocol === "https:";
        const webSocketProtocol = isSecureProtocol ? "wss" : "ws";
        const host = window.location.host // isDevelopment ? "localhost:7860" : window.location.host;
        const chatEndpoint = version === 'v1' ? `/api/v1/chat/${flowId}?type=L1&chat_id=${chatId}`
            : `/api/v2/chat/ws/${flowId}?type=L1&chat_id=${chatId}${libId ? '&knowledge_id=' + libId : ''}`

        return `${webSocketProtocol}://${host}${chatEndpoint}`;
    }

    function connectWS({ setInputState, setIsStop, changeHistoryByScroll }) {
        return new Promise((res, rej) => {
            try {
                const urlWs = getWebSocketUrl(
                    flow.id,
                    process.env.NODE_ENV === "development"
                );
                const newWs = new WebSocket(urlWs);
                newWs.onopen = () => {
                    setInputState({ lock: false, errorCode: '' });
                    console.log("WebSocket connection established!");
                    res('ok')
                    // heartbeat()
                };
                newWs.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    handleWsMessage({ data, setIsStop, setInputState, changeHistoryByScroll });
                    // get chat history
                    // 群聊@自己时，开启input
                    if (data.type === 'end' && data.receiver?.is_self) {
                        setInputState({ lock: false, errorCode: '' })
                    }
                };
                newWs.onclose = (event) => {
                    handleOnClose({ event, setIsStop, setInputState });
                };
                newWs.onerror = (ev) => {
                    console.error('error', ev);
                    setIsStop(true)

                    if (flow.id === "") {
                        // connectWS();
                    } else {
                        setErrorData({
                            title: `${t('chat.networkError')}:`,
                            list: [
                                t('chat.networkErrorList1'),
                                t('chat.networkErrorList2'),
                                t('chat.networkErrorList3')
                            ],
                        });
                    }
                };
                ws.current = newWs;
                console.log('newWs :>> ', newWs);
            } catch (error) {
                console.log(error);
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
            setInputState({ lock: false, errorCode: '' });
            changeHistoryByScroll.current = true
        }
        if (data.type === "start") {
            setChatHistory((old) => {
                let newChat = _.cloneDeep(old);
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
            console.log('newchats :>> ', newChats);
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
                ws.current.send(JSON.stringify(data));
            }
        } catch (error) {
            setErrorData({
                title: "There was an error sending the message",
                list: [error.message],
            });
        }
    }


    function handleOnClose({ event, setIsStop, setInputState }) {
        console.error('链接断开 event :>> ', event);
        setIsStop(true)
        setBegin(false)

        if ([1005, 1008].includes(event.code)) {
            setInputState({ lock: true, errorCode: String(event.code) });
        } else {
            if (event.reason) {
                setErrorData({ title: event.reason });
                setChatHistory((old) => {
                    let newChat = _.cloneDeep(old);
                    if (newChat.length) {
                        newChat[newChat.length - 1].end = true;
                    }
                    newChat.push({ end: true, message: `${t('chat.connectionbreakTip')}${event.reason}`, isSend: false, chatKey: '', files: [] });
                    return newChat
                })
            }
            setInputState({ lock: false, errorCode: '' });
        }

        ws.current?.close()
        ws.current = null
    }

    useEffect(() => {
        return () => {
            if (ws.current) {
                ws.current.close();
            }
        };
    }, []);

    const closeWs = () => {
        // close prev connection
        if (ws.current) {
            switch (ws.current.readyState) {
                case WebSocket.OPEN:
                    ws.current.close()
                    ws.current = null
                        ; break;
                case WebSocket.CONNECTING:
                    ws.current.onopen = () => {
                        ws.current.close()
                    };
            }
        }
    }

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

    return { begin, stop: handleStop, checkReLinkWs, sendAll, connectWS, closeWs }
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
        const response = await postBuildInit(flow, chatId);
        const { flowId } = response.data;
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


// 有帮助 没有帮助
const useHelpful=(messages,chatId,chating,inputState,onReload,setInputState)=>{
    const { setErrorData, setSuccessData } = useContext(alertContext);
    const { t } = useTranslation()
    
    const {helpful,helpless} = useMemo(()=>{
        const handle=async(solved)=>{
           
            try {
                setInputState({
                    lock:true,
                    errorCode:""
                })
                await chatResolved({chatId,solved})
                setSuccessData({title: t('chat.resoledSuccess')})
                 onReload()
            } catch (error) {
                console.error("Error:", error);
                setErrorData({
                    title:error.message
                })
            }finally{
                setInputState({
                    lock:false,
                    errorCode:""
                })
            }
          
        }
        return {
            helpful:()=>handle(1),
            helpless:()=>handle(2),
        }
    },[chatId,onReload,t,setInputState])

    const show = useMemo(()=>{
        /* 
            何时展示 有帮助/没有帮助
            1、没有对话内容  不展示
            2、最后一条信息不是机器人发送的消息 不展示
            3、最后一条机器人消息未完成 不展示
            4、其余情况     展示
        */
        if(chating || !messages.length) return false;
        const lastMessage = messages[messages.length-1]
        if(lastMessage.isSend) return false;
        return  true
    },[messages,chating])

    if(!show) return null;
    return  <div className="w-full flex  gap-x-3 ">
                <Button 
                className="rounded-full"
                variant="outline" 
                disabled={inputState?.lock}
                onClick={helpful}>
                    <StopCircle className="mr-2" />
                    {t('chat.helpful')}
                </Button>

                <Button 
                className="rounded-full" 
                variant="outline" 
                disabled={inputState?.lock}
                onClick={helpless}>
                    <StopCircle className="mr-2" />
                    {t('chat.helpless')}
                </Button>
            </div>
}