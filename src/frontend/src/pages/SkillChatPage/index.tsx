import { t } from "i18next";
import _ from "lodash";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { alertContext } from "../../contexts/alertContext";
import { TabsContext } from "../../contexts/tabsContext";
import { deleteChatApi, getChatHistory, getChatsApi, getFlowFromDatabase, postBuildInit, postValidatePrompt, readOnlineFlows } from "../../controllers/API";
import { uploadFileWithProgress } from "../../modals/UploadModal/upload";
import { sendAllProps } from "../../types/api";
import { ChatMessageType } from "../../types/chat";
import { FlowType, NodeType } from "../../types/flow";
import { generateUUID, validateNode } from "../../utils";
import SkillTemps from "../SkillPage/components/SkillTemps";
import ChatPanne from "./components/ChatPanne";
import { Trash2 } from "lucide-react";
import { bsconfirm } from "../../alerts/confirm";
// import ChatReportForm from "./components/ChatReportForm";

export default function SkillChatPage() {
    const [open, setOpen] = useState(false)
    const [face, setFace] = useState(true);

    const { t } = useTranslation()

    const { flows } = useContext(TabsContext);
    const [flow, setFlow] = useState<FlowType>(null)
    const [onlineFlows, setOnlineFlows] = useState([])
    useEffect(() => {
        readOnlineFlows().then(res => setOnlineFlows(res))
    }, [])
    // 对话列表
    const { chatList, chatId, chatsRef, setChatId, addChat, deleteChat } = useChatList()
    const chatIdRef = useRef('')
    const {
        isReport,
        isRoom,
        inputState,
        fileInputs,
        chating,
        stopState,
        stopClick,
        uploadFile,
        setInputState,
        changeHistoryByScroll,
        chatHistory,
        clearHistory,
        initChat,
        sendMsg,
        sendReport,
        loadNextPage
    } = useWebsocketChat(chatIdRef) // talk
    // select flow
    const handlerSelectFlow = async (node: FlowType) => {
        // 会话ID
        chatIdRef.current = generateUUID(32)
        setOpen(false)
        setFlow(node)
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

        if (inputRef.current) inputRef.current.value = ''
        setTimeout(() => {
            inputRef.current?.focus()
        }, 500);
    }

    // select chat
    const handleSelectChat = async (chat) => {
        if (chat.chat_id === chatId) return
        setChatId(chat.chat_id)
        chatIdRef.current = chat.chat_id
        let flow = flows.find(flow => flow.id === chat.flow_id) || await getFlowFromDatabase(chat.flow_id)

        if (!flow) {
            setInputState({ lock: true, errorCode: '1004' })
            clearHistory()
            return setFace(false)
        }
        setFlow(flow)
        await initChat(flow)
        setFace(false)

        changeHistoryByScroll.current = false
        // focus
        setTimeout(() => {
            inputRef.current?.focus()
        }, 500);
    }

    // 输入问答
    const inputRef = useRef(null)
    useEffect(() => {
        !chating && setTimeout(() => {
            // 对话结束自动聚焦
            inputRef.current?.focus()
        }, 1000);
    }, [chating])

    // del
    const handleDeleteChat = (e, id) => {
        e.stopPropagation();
        bsconfirm({
            desc: t('chat.confirmDeleteChat'),
            onOk(next) {
                deleteChat(id);
                setFace(true)
                next()
            }
        })
    }

    // sendmsg user name
    const sendUserName = useMemo(() => {
        if (flow) {
            const node = flow.data.nodes.find(el => el.data.type === 'AutoGenUser')
            return node?.data.node.template['name'].value || ''
        }
        return ''
    }, [flow])

    return <div className="flex">
        <div className="h-screen w-[200px] relative border-r">
            <div className="absolute flex pt-2 ml-[20px] bg-[#fff] dark:bg-gray-950">
                <div className="border rounded-lg px-4 py-2 text-center text-sm cursor-pointer w-[160px] bg-gray-50 hover:bg-gray-100 dark:hover:bg-gray-800 relative z-10" onClick={() => setOpen(true)}>{t('chat.newChat')}</div>
            </div>
            <div ref={chatsRef} className="scroll p-4 h-full overflow-y-scroll no-scrollbar pt-12">
                {
                    chatList.map((chat, i) => (
                        <div key={chat.chat_id}
                            className={` group item rounded-xl mt-2 p-2 relative hover:bg-gray-100 cursor-pointer  dark:hover:bg-gray-800  ${chatId === chat.chat_id && 'bg-gray-100 dark:bg-gray-800'}`}
                            onClick={() => handleSelectChat(chat)}>
                            <p className="break-words text-sm font-bold text-gray-600">{chat.flow_name}</p>
                            <span className="text-xs text-gray-500">{chat.flow_description}</span>
                            <Trash2 size={14} className="absolute bottom-2 right-2 text-gray-400 hidden group-hover:block" onClick={(e) => handleDeleteChat(e, chat.chat_id)}></Trash2>
                        </div>
                    ))
                }
            </div>
        </div>
        {/* chat */}
        {face
            ? <div className="flex-1 chat-box h-screen overflow-hidden relative">
                <p className="text-center mt-[100px] text-sm text-gray-600">{t('chat.selectChat')}</p>
            </div>
            : <div className="flex-1 chat-box h-screen relative">
                <ChatPanne
                    ref={inputRef}
                    isRoom={isRoom}
                    isReport={isReport}
                    fileInputs={fileInputs}
                    inputState={inputState}
                    chatId={chatId}
                    messages={chatHistory}
                    flowName={chatList.find(chat => chat.chat_id === chatId)?.flow_name}
                    changeHistoryByScroll={changeHistoryByScroll.current}
                    stopState={stopState}
                    sendUserName={sendUserName}
                    onStopClick={stopClick}
                    onSendMsg={sendMsg}
                    onNextPageClick={loadNextPage}
                    onUploadFile={uploadFile}
                />
                {/* {isReport && !chatHistory.length && <ChatReportForm flow={flow} onStart={sendReport} />} */}
            </div>}
        {/* 选择对话技能 */}
        <SkillTemps
            flows={onlineFlows}
            title={t('chat.skillTempsTitle')}
            desc={t('chat.skillTempsDesc')}
            open={open} setOpen={setOpen}
            onSelect={(e) => handlerSelectFlow(e)}></SkillTemps>
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
    const { t } = useTranslation()

    const { tabsState } = useContext(TabsContext);
    const [inputState, setInputState] = useState({
        lock: false,
        errorCode: ''
    })

    const build = useBuild() // build
    const { setErrorData } = useContext(alertContext);
    // 聊天记录
    const [chatHistory, setChatHistory] = useState<ChatMessageType[]>([]);
    const loadHistory = async (lastId?: number) => {
        const res = await getChatHistory(flow.current.id, chatIdRef.current, lastId ? 10 : 30, lastId)
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
                    setInputState({ lock: false, errorCode: '' });
                    console.log("WebSocket connection established!");
                    res('ok')
                    // heartbeat()
                };
                newWs.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    handleWsMessage(data);
                    // get chat history
                    // 群聊@自己时，开启input
                    if (data.type === 'end' && data.receiver?.is_self) {
                        setInputState({ lock: false, errorCode: '' })
                    }
                };
                newWs.onclose = (event) => {
                    handleOnClose(event);
                };
                newWs.onerror = (ev) => {
                    console.error('error', ev);
                    setIsStop(true)

                    if (flow.current.id === "") {
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
        setInputState({ lock: true, errorCode: '' });
        let inputs = tabsState[flow.current.id].formKeysData.input_keys;
        const input = inputs.find((el: any) => !el.type)
        const inputKey = Object.keys(input)[0];
        addChatHistory({
            isSend: true,
            message: { ...input, [inputKey]: msg },
            chatKey: inputKey
        })
        await checkReLinkWs()

        // @ts-ignore
        isRoom && begin ? sendAll({ action: "continue", "inputs": { ...input, [inputKey]: msg } })
            : sendAll({
                ...flow.current.data,
                inputs: { ...input, [inputKey]: msg },
                chatHistory,
                name: flow.current.name,
                description: flow.current.description,
            });
    }

    // 报表请求 TODO
    const sendReport = (obj, str) => {
        let inputs = tabsState[flow.current.id].formKeysData.input_keys;
        const input = inputs.find((el: any) => !el.type)
        const inputKey = Object.keys(input)[0];
        addChatHistory({
            isSend: true,
            message: { ...input, [inputKey]: str },
            chatKey: inputKey
        })

        addChatHistory({
            isSend: false,
            files: [{
                file_name: '报表结果.docx',
                file_url: 'http://192.168.2.15:3001/new.docx'
            }]
        })
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
            // setChatHistory((_) => {
            //     let newChatHistory: ChatMessageType[] = [];
            //     data.forEach(
            //         (chatItem: {
            //             intermediate_steps?: string;
            //             is_bot: boolean;
            //             message: string;
            //             template: string;
            //             type: string;
            //             chatKey: string;
            //             files?: Array<any>;
            //         }) => {
            //             if (chatItem.message) {
            //                 newChatHistory.push(
            //                     chatItem.files
            //                         ? {
            //                             isSend: !chatItem.is_bot,
            //                             message: chatItem.message,
            //                             template: chatItem.template,
            //                             thought: chatItem.intermediate_steps,
            //                             files: chatItem.files,
            //                             chatKey: chatItem.chatKey,
            //                             end: true
            //                         }
            //                         : {
            //                             isSend: !chatItem.is_bot,
            //                             message: chatItem.message,
            //                             template: chatItem.template,
            //                             thought: chatItem.intermediate_steps,
            //                             chatKey: chatItem.chatKey,
            //                             end: true
            //                         }
            //                 );
            //             }
            //         }
            //     );
            //     return newChatHistory;
            // });
            return
        }
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
            // TODO 分割线  群聊情况下
        }
        if (data.type === "start") {
            addChatHistory({
                isSend: false,
                thought: data.intermediate_steps,
                category: data.category
            })
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
            });

            isStream = false;
        }
    }

    //add proper type signature for function
    const addChatHistory = (data: {
        isSend: boolean,
        message?: string | Object,
        chatKey?: string,
        thought?: string,
        category?: string,
        files?: Array<any>,
        end?: boolean
    }) => {
        setChatHistory((old) => {
            let newChat = _.cloneDeep(old);
            newChat.push({
                isSend: data.isSend,
                message: data.message || '',
                chatKey: data.chatKey || '',
                thought: data.thought || '',
                category: data.category || '',
                files: data.files || [],
                end: data.end || false
            })
            return newChat
        });
    };

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
                end,
                // user_id
                // user_name
                // at
            }
            newChats[chatsLen - 1] = newLastChat
            // start - end 之间没有内容删除load
            if (end && !(newLastChat.files.length || newLastChat.thought || newLastChat.message)) {
                newChats.pop()
            }
            return newChats;
        });
    }

    function handleOnClose(event: CloseEvent) {
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

        // setTimeout(() => {
        // connectWS();
        // setLockChat(false);
        // }, 1000);
    }

    useEffect(() => {
        return () => {
            if (ws.current) {
                ws.current.close();
            }
        };
    }, []);

    // 获取上传file input
    const fileInputs = useMemo(() => {
        if (!flow.current) return
        return tabsState[flow.current.id]?.formKeysData?.input_keys?.filter((input: any) => input.type === 'file')
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
        // 添加一条记录
        addChatHistory({
            isSend: true,
            files: [{
                file_name: file.name,
                data: 'progress',
                data_type: 'PDF'
            }]
        });
        await checkReLinkWs()
        setInputState({ lock: true, errorCode: '' });
        uploadFileWithProgress(file, (count) => { }).then(data => {
            setChatHistory((old) => {
                let newChat = [...old];
                newChat[newChat.length - 1].files[0].data = data ? '' : 'error'
                return newChat;
            })

            if (!data) return setInputState({ lock: false, errorCode: '' });
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

    // 是否群聊
    const isRoom = useMemo(() => {
        return !!flow.current?.data.nodes.find(node => node.data.type === "AutoGenChain")
    }, [flow.current])

    // 是否报表表单
    const isReport = useMemo(() => {
        // 如果有 VariableNode  inputnode 就属于
        return !!flow.current?.data.nodes.find(node => ["VariableNode", "InputFileNode1"].includes(node.data.type))
    }, [flow.current])

    // 停止状态
    const [isStop, setIsStop] = useState(true)
    return {
        isRoom,
        isReport,
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
        },
        stopState: isStop,
        sendReport,
        stopClick: () => {
            setIsStop(true)
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
                //   setChatValue(data.inputs);
                // connectWS();
            }
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
                    title: t('chat.buildError'),
                    list: errors,
                });
                return;
            }

            const minimumLoadingTime = 200; // in milliseconds
            const startTime = Date.now();

            await streamNodeData(flow, chatIdRef.current);
            await enforceMinimumLoadingTime(startTime, minimumLoadingTime); // 至少等200ms, 再继续(强制最小load时间)

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
    const [id, setId] = useState('')
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
        },
        deleteChat: (id: string) => {
            // api
            deleteChatApi(id)
            setChatList(oldList => oldList.filter(item => item.chat_id !== id))
        }
    }
}