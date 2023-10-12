import _ from "lodash";
import { FileUp, Send } from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import ShadTooltip from "../../components/ShadTooltipComponent";
import { alertContext } from "../../contexts/alertContext";
import { TabsContext } from "../../contexts/tabsContext";
import { getChatHistory, getChatsApi, getFlowFromDatabase, postBuildInit, postValidatePrompt, readOnlineFlows } from "../../controllers/API";
import { uploadFileWithProgress } from "../../modals/UploadModal/upload";
import { sendAllProps } from "../../types/api";
import { ChatMessageType } from "../../types/chat";
import { FlowType, NodeType } from "../../types/flow";
import { generateUUID, validateNode } from "../../utils";
import SkillTemps from "../SkillPage/components/SkillTemps";
import { ChatMessage } from "./components/ChatMessage";
import ResouceModal from "./components/ResouceModal";

export default function SkillChatPage(params) {
    const [open, setOpen] = useState(false)
    const [face, setFace] = useState(true);

    const { flows } = useContext(TabsContext);
    const [onlineFlows, setOnlineFlows] = useState([])
    useEffect(() => {
        readOnlineFlows().then(res => setOnlineFlows(res))
    }, [])
    // 对话列表
    const { chatList, chatId, chatsRef, setChatId, addChat } = useChatList()

    const chatIdRef = useRef('')
    const {
        inputState,
        fileInputs,
        chating,
        uploadFile,
        setInputState,
        changeHistoryByScroll,
        chatHistory,
        clearHistory,
        initChat,
        sendMsg,
        loadNextPage
    } = useWebsocketChat(chatIdRef) // talk
    // select flow
    const handlerSelectFlow = async (node: FlowType) => {
        // 会话ID
        chatIdRef.current = generateUUID(32)
        setOpen(false)
        await initChat(node)
        setFace(false)
        // add list
        addChat({
            "flow_name": node.name,
            "flow_description": node.description,
            "flow_id": node.id,
            "chat_id": chatIdRef.current,
            "create_time": "-",
            "update_time": "-"
        })

        inputRef.current.value = ''
        setInputEmpty(true)

        setTimeout(() => {
            inputRef.current.focus()
        }, 500);
    }

    // select chat
    const handleSelectChat = async (chat) => {
        if (chat.chat_id === chatId) return
        setChatId(chat.chat_id)
        chatIdRef.current = chat.chat_id
        let flow = flows.find(flow => flow.id === chat.flow_id) || await getFlowFromDatabase(chat.flow_id)
        if (!flow) {
            setInputState({ lock: true, error: '该技能已被删除' })
            clearHistory()
            return setFace(false)
        }
        await initChat(flow)
        setFace(false)

        if (inputRef.current) inputRef.current.value = ''
        setInputEmpty(true)
        changeHistoryByScroll.current = false
        // focus
        setTimeout(() => {
            inputRef.current.focus()
        }, 500);
    }

    // 输入问答
    const inputRef = useRef(null)
    const inputDisable = inputState.lock || (fileInputs?.length && chatHistory.length === 0)
    const handleSend = () => {
        const val = inputRef.current.value
        setTimeout(() => {
            inputRef.current.value = ''
            inputRef.current.style.height = 'auto'
            setInputEmpty(true)
        }, 100);

        if (val.trim() === '' || inputDisable) return
        sendMsg(val)
    }
    useEffect(() => {
        !chating && setTimeout(() => {
            // 对话结束自动聚焦
            inputRef.current?.focus()
        }, 1000);
    }, [chating])

    // input 滚动
    const [inputEmpty, setInputEmpty] = useState(true)
    const handleTextAreaHeight = (e) => {
        const textarea = e.target
        textarea.style.height = 'auto'
        textarea.style.height = textarea.scrollHeight + 'px'
        setInputEmpty(textarea.value.trim() === '')
    }

    // 消息滚动
    const messagesRef = useRef(null);
    useEffect(() => {
        if (messagesRef.current && !changeHistoryByScroll.current) { // 滚动加载不触发
            messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
        }
    }, [chatHistory, changeHistoryByScroll.current]);

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

    // 溯源
    const [souce, setSouce] = useState<ChatMessageType>(null)

    return <div className="flex">
        <div className="h-screen w-[200px] relative border-r">
            <div className="absolute flex pt-2 ml-[20px] bg-[#fff] dark:bg-gray-950">
                <div className="border rounded-lg px-4 py-2 text-center cursor-pointer w-[160px] hover:bg-gray-100 dark:hover:bg-gray-800" onClick={() => setOpen(true)}>新建会话</div>
            </div>
            <div ref={chatsRef} className="scroll p-4 h-full overflow-y-scroll no-scrollbar pt-12">
                {
                    chatList.map((chat, i) => (
                        <div key={chat.chat_id} className={`item rounded-xl mt-2 p-2 hover:bg-gray-100 cursor-pointer  dark:hover:bg-gray-800  ${chatId === chat.chat_id && 'bg-gray-100 dark:bg-gray-800'}`} onClick={() => handleSelectChat(chat)}>
                            <p className="">{chat.flow_name}</p>
                            <span className="text-xs text-gray-500">{chat.flow_description}</span>
                        </div>
                    ))
                }
            </div>
        </div>
        {/* chat */}
        {face ? <div className="flex-1 chat-box h-screen overflow-hidden relative">
            <p className="text-center mt-[100px]">选择一个对话开始文擎睿见</p>
        </div>
            : <div className="flex-1 chat-box h-screen overflow-hidden relative">
                <div className="absolute w-full px-4 py-4 bg-[#fff] z-10 dark:bg-gray-950">{chatList.find(chat => chat.chat_id === chatId)?.flow_name}</div>
                <div className="chata mt-14" style={{ height: 'calc(100vh - 5rem)' }}>
                    <div ref={messagesRef} className="chat-panne h-full overflow-y-scroll no-scrollbar px-4 pb-20">
                        {
                            chatHistory.map((c, i) => <ChatMessage key={i} chat={c} onSouce={() => setSouce(c)}></ChatMessage>)
                        }
                        {/* <div className="chat chat-start">
                        <div className="chat-bubble chat-bubble-info bg-gray-300">It's over Anakin, <br />I have the high ground.</div>
                        <div className="chat-footer flex text-xs pt-2">
                            <span className="opacity-50">来源:</span>
                            <ul>
                                <li><a href="#" className="text-blue-600">一个PDF.pdf</a></li>
                                <li><a href="#" className="text-blue-600">量个PDF.pdf</a></li>
                                <li><a href="#" className="text-blue-600">网页地址</a></li>
                                <li><a href="#" className="text-blue-600">sql语句</a></li>
                            </ul>
                        </div>
                    </div> */}
                    </div>
                    <div className="absolute w-full bottom-0 bg-gradient-to-t from-[#fff] to-[rgba(255,255,255,0.8)] px-8 dark:bg-gradient-to-t dark:from-[#000] dark:to-[rgba(0,0,0,0.8)]">
                        <div className={`w-full text-area-box border border-gray-600 rounded-lg my-6 overflow-hidden pr-2 py-2 relative ${(inputState.lock || (fileInputs?.length && chatHistory.length === 0)) && 'bg-gray-200 dark:bg-gray-600'}`}>
                            <textarea id='input'
                                ref={inputRef}
                                disabled={inputDisable} style={{ height: 36 }} rows={1}
                                className={`w-full resize-none border-none bg-transparent outline-none px-4 pt-1 text-xl max-h-[200px]`}
                                placeholder="请输入问题"
                                onInput={handleTextAreaHeight}
                                onKeyDown={(event) => {
                                    if (event.key === "Enter" && !event.shiftKey) handleSend()
                                }}></textarea>
                            <div className="absolute right-6 bottom-4 flex gap-2">
                                <ShadTooltip content={'上传文件'}>
                                    <button disabled={inputState.lock || !fileInputs?.length} className="disabled:text-gray-400" onClick={uploadFile}><FileUp /></button>
                                </ShadTooltip>
                                <ShadTooltip content={'发送'}>
                                    {/* 内容为空 or 输入框禁用 or 文件分析类未上传文件 */}
                                    <button disabled={inputEmpty || inputDisable} className=" disabled:text-gray-400" onClick={handleSend}><Send /></button>
                                </ShadTooltip>
                            </div>
                            {inputState.error && <div className="bg-gray-200 absolute top-0 left-0 w-full h-full text-center text-gray-400 align-middle pt-4">{inputState.error}</div>}
                        </div>
                    </div>
                </div>
            </div>}
        {/* 添加模型 */}
        <SkillTemps
            flows={onlineFlows}
            title='技能选择'
            desc='选择一个您想使用的线上技能'
            open={open} setOpen={setOpen}
            onSelect={(e) => handlerSelectFlow(e)}></SkillTemps>
        {/* 源文件类型 */}
        <ResouceModal chatId={chatIdRef.current} open={!!souce} data={souce} setOpen={() => setSouce(null)}></ResouceModal>
    </div>
};
/**
 * 聊天
 * 发送（chatHistory, desc, inputs, name, deges, nodes, viewport）
 * 接收存chatHistory({chatKey, isSend, message{k: v}} & {thought}[])
 */
const useWebsocketChat = (chatIdRef) => {
    const ws = useRef<WebSocket | null>(null);
    const flow = useRef<FlowType>(null)

    const { tabsState } = useContext(TabsContext);
    const [inputState, setInputState] = useState({
        lock: false,
        error: ''
    })

    const build = useBuild() // build
    const { setErrorData } = useContext(alertContext);
    // 聊天记录
    const [chatHistory, setChatHistory] = useState<ChatMessageType[]>([]);
    const loadHistory = async (lastId?: number) => {
        const res = await getChatHistory(flow.current.id, chatIdRef.current, lastId ? 10 : 30, lastId)
        const hisData = res.map(item => {
            // let count = 0
            let message = item.message
            try {
                message = item.message && item.message[0] === '{' ? JSON.parse(item.message.replace(/([\t\n"])/g, '\\$1').replace(/'/g, '"')) : item.message || ''
            } catch (e) {
                // 未考虑的情况暂不处理
                message = item.message
            }
            return {
                chatKey: typeof message === 'string' ? undefined : Object.keys(message)[0],
                end: true,
                files: item.files ? JSON.parse(item.files) : null,
                isSend: !item.is_bot,
                message,
                thought: item.intermediate_steps,
                id: item.id,
                category: item.category,
                source: item.source
            }
        })
        lastIdRef.current = hisData[hisData.length - 1]?.id || lastIdRef.current // 记录最后一个id
        setChatHistory((history) => [...hisData.reverse(), ...history])
    }
    const loadLock = useRef(false)
    const currentIdRef = useRef(0)
    const lastIdRef = useRef(0)
    // 控制开启自动随消息滚动（临时方案）
    const changeHistoryByScroll = useRef(false)
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

    function getWebSocketUrl(_chatId, isDevelopment = false) {
        const isSecureProtocol = window.location.protocol === "https:";
        const webSocketProtocol = isSecureProtocol ? "wss" : "ws";
        const host = window.location.host // isDevelopment ? "localhost:7860" : window.location.host;
        const chatEndpoint = `/api/v1/chat/${_chatId}?type=L1&chat_id=${chatIdRef.current}`;

        return `${webSocketProtocol}://${host}${chatEndpoint}`;
    }

    function heartbeat() {
        if (!ws.current) return;
        if (ws.current.readyState !== 1) return;
        ws.current.send("heartbeat");
        setTimeout(heartbeat, 30000);
    }
    function connectWS() {
        return new Promise((res, rej) => {
            try {
                const urlWs = getWebSocketUrl(
                    flow.current.id,
                    process.env.NODE_ENV === "development"
                );
                const newWs = new WebSocket(urlWs);
                newWs.onopen = () => {
                    setInputState({ lock: false, error: '' });
                    console.log("WebSocket connection established!");
                    res('ok')
                    // heartbeat()
                };
                newWs.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    handleWsMessage(data);
                    //get chat history
                };
                newWs.onclose = (event) => {
                    handleOnClose(event);
                };
                newWs.onerror = (ev) => {
                    console.error('error', ev);
                    if (flow.current.id === "") {
                        // connectWS();
                    } else {
                        setErrorData({
                            title: "网络连接出现错误,请尝试以下方法: ",
                            list: [
                                "操作不要过快",
                                "刷新页面",
                                "检查后台是否启动"
                            ],
                        });
                    }
                };
                ws.current = newWs;
                console.log('newWs :>> ', newWs);
            } catch (error) {
                if (flow.current.id === "") {
                    // connectWS();
                }
                console.log(error);
                rej(error)
            }
        })
    }

    // send
    const sendMsg = async (msg) => {
        setInputState({ lock: true, error: '' });
        let inputs = tabsState[flow.current.id].formKeysData.input_keys;
        const input = inputs.find((el: any) => !el.type)
        const inputKey = Object.keys(input)[0];
        addChatHistory(
            { ...input, [inputKey]: msg },
            true,
            inputKey,
            tabsState[flow.current.id].formKeysData.template
        );
        await checkReLinkWs()

        sendAll({
            ...flow.current.data,
            inputs: { ...input, [inputKey]: msg },
            chatHistory,
            name: flow.current.name,
            description: flow.current.description,
        });
        // setTabsState((old) => {
        //     if (!chatKey) return old;
        //     let newTabsState = _.cloneDeep(old);
        //     newTabsState[id.current].formKeysData.input_keys[chatKey] = ""; // input值制空
        //     return newTabsState;
        // });
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
            //   setChatValue(data.inputs);
            // connectWS();
        }
    }

    var isStream = false;
    // 接收ws
    const [begin, setBegin] = useState(false)
    function handleWsMessage(data: any) {
        if (Array.isArray(data) && data.length) {
            //set chat history
            setChatHistory((_) => {
                let newChatHistory: ChatMessageType[] = [];
                data.forEach(
                    (chatItem: {
                        intermediate_steps?: string;
                        is_bot: boolean;
                        message: string;
                        template: string;
                        type: string;
                        chatKey: string;
                        files?: Array<any>;
                    }) => {
                        if (chatItem.message) {
                            newChatHistory.push(
                                chatItem.files
                                    ? {
                                        isSend: !chatItem.is_bot,
                                        message: chatItem.message,
                                        template: chatItem.template,
                                        thought: chatItem.intermediate_steps,
                                        files: chatItem.files,
                                        chatKey: chatItem.chatKey,
                                        end: true
                                    }
                                    : {
                                        isSend: !chatItem.is_bot,
                                        message: chatItem.message,
                                        template: chatItem.template,
                                        thought: chatItem.intermediate_steps,
                                        chatKey: chatItem.chatKey,
                                        end: true
                                    }
                            );
                        }
                    }
                );
                return newChatHistory;
            });
        }
        if (data.type === "begin") {
            setBegin(true)
            changeHistoryByScroll.current = false
        }
        if (data.type === "close") {
            setBegin(false)
            setInputState({ lock: false, error: '' });
            changeHistoryByScroll.current = true
        }
        // 日志分析 (独立一条)
        // if (data.intermediate_steps) {
        //     addChatHistory( '', false, undefined, '', data.intermediate_steps, data.category );
        // }
        if (data.type === "start") {
            addChatHistory("", false, undefined, '', data.intermediate_steps || '', data.category || '');
            isStream = true;
        }
        if (data.type === "stream" && isStream) {
            updateLastMessage({ str: data.message, thought: data.intermediate_steps });
        }
        if (data.type === "end") {
            updateLastMessage({
                str: data.message,
                files: data.files || null,
                end: true,
                thought: data.intermediate_steps || '',
                cate: data.category || '',
                messageId: data.message_id,
                source: data.source
            });
            // if (data.message) {
            //     updateLastMessage({ str: data.message, end: true });
            // } else if (data.files) {
            //     updateLastMessage({
            //         end: true,
            //         files: data.files,
            //     });
            // }

            isStream = false;
        }
    }

    //add proper type signature for function
    const addChatHistory = (
        message: string | Object,
        isSend: boolean,
        chatKey: string,
        template?: string,
        thought?: string,
        category?: string,
        files?: Array<any>
    ) => {
        setChatHistory((old) => {
            const end = false
            let newChat = _.cloneDeep(old);
            if (files) {
                newChat.push({ end, message, isSend, thought, category, chatKey, files });
            } else if (thought) {
                newChat.push({ end, message, isSend, thought, category, chatKey });
            } else if (template) {
                newChat.push({ end, message, isSend, template, chatKey });
            } else {
                newChat.push({ end, message, isSend, thought: '', category, chatKey });
            }
            return newChat;
        });
    };

    function updateLastMessage({ str, thought, end = false, files, cate, messageId, source }: {
        str?: string;
        thought?: string;
        cate?: string;
        // end param default is false
        end?: boolean;
        files?: Array<any>;
        messageId?: number
        source?: boolean
    }) {
        setChatHistory((old) => {
            let newChat = [...old];
            const lastChat = newChat[newChat.length - 1]
            // hack 过滤重复最后消息
            if (end && str && newChat.length > 1 && str === newChat[newChat.length - 2].message && !newChat[newChat.length - 2].thought) {
                newChat.pop()
                return newChat
            }
            if (end) {
                // 最后全集msg
                lastChat.end = true;
            }
            if (str) {
                // 累加msg
                lastChat.message += str;
            }
            if (thought) {
                lastChat.thought += thought + '\n';
            }
            if (files) {
                lastChat.files = files;
            }
            if (cate) {
                lastChat.category = cate;
            }
            if (messageId) {
                lastChat.id = messageId;
            }
            if (source) {
                lastChat.source = source;
            }
            // start - end 之间没有内容删除load
            if (end && !(lastChat.files?.length || lastChat.thought || lastChat.message)) {
                newChat.pop()
            }
            return newChat;
        });
    }

    function handleOnClose(event: CloseEvent) {
        console.error('链接断开 event :>> ', event);
        if ([1005, 1008].includes(event.code)) {
            setInputState({ lock: true, error: event.reason });
        } else {
            setErrorData({ title: event.reason });
            setChatHistory((old) => {
                let newChat = _.cloneDeep(old);
                if (!newChat.length) return []
                newChat[newChat.length - 1].end = true;
                newChat.push({ end: true, message: event.reason ? '链接异常断开:' + event.reason : '网络断开！', isSend: false, chatKey: '' });
                return newChat
            })
            setInputState({ lock: false, error: '' });
        }

        ws.current?.close()
        ws.current = null

        setTimeout(() => {
            // connectWS();
            // setLockChat(false);
        }, 1000);
    }

    useEffect(() => {
        return () => {
            if (ws.current) {
                ws.current.close();
            }
        };
        // do not add connectWS on dependencies array
    }, []);

    // 获取上传file input
    const fileInputs = useMemo(() => {
        if (!flow.current) return
        return tabsState[flow.current.id]?.formKeysData.input_keys?.filter((input: any) => input.type === 'file')
    }, [tabsState, flow.current])

    // 上传文件
    const uploadFile = () => {
        const config = fileInputs?.[0]
        if (!config) return
        // 判断上传类型
        const node = flow.current.data.nodes.find(el => el.id === config.id)
        const accept = node.data.node.template.file_path.suffixes.join(',')

        var input = document.createElement('input');
        input.type = 'file';
        input.accept = accept;
        input.style.display = 'none';
        input.addEventListener('change', (e) => handleFileSelect(e, input));
        document.body.appendChild(input);
        input.click(); // 触发文件选择对话框
    }

    async function handleFileSelect(event, input) {
        const config: any = fileInputs?.[0]
        var file = event.target.files[0];
        // if (file.type !== 'application/pdf') {
        //     return setErrorData({
        //         title: "只能上传pdf文件",
        //         // list: ['1', '2'],
        //     })
        // }
        // 添加一条记录
        addChatHistory(
            {},
            true,
            '',
            undefined,
            undefined,
            undefined,
            [{
                file_name: file.name,
                data: 'progress',
                data_type: 'PDF'
            }]
        );
        await checkReLinkWs()
        setInputState({ lock: true, error: '' });
        uploadFileWithProgress(file, (count) => { }).then(data => {
            setChatHistory((old) => {
                let newChat = [...old];
                newChat[newChat.length - 1].files[0].data = data ? '' : 'error'
                return newChat;
            })

            if (!data) return setInputState({ lock: false, error: '' });
            // setFilePaths
            sendAll({
                ...flow.current.data,
                id: config.id,
                file_path: data.file_path,
                inputs: { ...config, file_path: data.file_path },
                chatHistory,
                name: flow.current.name,
                description: flow.current.description,
            });
            input.remove()
        })
    }

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
    const checkReLinkWs = async () => {
        if (ws.current) return true
        // 重新链接
        // 上一条加loading
        setChatHistory((old) => {
            let newChat = [...old];
            newChat[newChat.length - 1].category = 'loading';
            return newChat;
        });
        await build(flow.current, chatIdRef)
        await connectWS()
        // 链接成功
        // 上一条去loading
        setChatHistory((old) => {
            let newChat = [...old];
            newChat[newChat.length - 1].category = '';
            return newChat;
        });
    }

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

    return {
        chating: begin,
        inputState,
        fileInputs,
        chatHistory,
        uploadFile,
        setInputState,
        async initChat(_flow) {
            closeWs()
            await checkPrompt(_flow)
            await build(_flow, chatIdRef)
            setChatHistory([])
            flow.current = _flow
            connectWS()
            loadHistory()
        },
        sendMsg,
        loadNextPage,
        changeHistoryByScroll,
        clearHistory() {
            setChatHistory([])
        }
    }
}
/**
 * build flow
 * 校验每个节点，展示进度及结果；返回input_keys;end_of_stream断开链接
 * 主要校验节点并设置更新setTabsState的 formKeysData
 * @returns 
 */
const useBuild = () => {
    const { setErrorData } = useContext(alertContext);
    const { setTabsState } = useContext(TabsContext);

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

    async function handleBuild(flow: FlowType, chatIdRef: any) {
        try {
            const errors = flow.data.nodes.flatMap((n: NodeType) => validateNode(n, flow.data.edges))
            if (errors.length > 0) {
                setErrorData({
                    title: "您好像缺少了某些配置",
                    list: errors,
                });
                return;
            }

            const minimumLoadingTime = 200; // in milliseconds
            const startTime = Date.now();

            await streamNodeData(flow, chatIdRef.current);
            await enforceMinimumLoadingTime(startTime, minimumLoadingTime); // 至少等200ms, 再继续(强制最小load时间)

            // if (!allNodesValid) {
            //     setErrorData({
            //         title: "您好像缺少了某些配置",
            //         list: [
            //             "检查组件并重试。将鼠标悬停在组件状态图标 🔴 上进行检查。",
            //         ],
            //     });
            // }
        } catch (error) {
            console.error("Error:", error);
        } finally {
        }
    }

    return handleBuild
}

/**
 * 本地对话列表
 */
const useChatList = () => {
    const [id, setId] = useState(-1)
    const [chatList, setChatList] = useState([])
    const chatsRef = useRef(null)

    useEffect(() => {
        getChatsApi().then(setChatList)
    }, [])

    return {
        chatList,
        chatId: id,
        chatsRef,
        setChatId: setId,
        addChat: (chat) => {
            const newList = [chat, ...chatList]
            // localStorage.setItem(ITEM_KEY, JSON.stringify(newList))
            setChatList(newList)
            setId(chat.chat_id)
            setTimeout(() => {
                chatsRef.current.scrollTop = 1
            }, 0);
        }
    }
}