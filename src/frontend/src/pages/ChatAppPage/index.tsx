import { Trash2 } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { NewApplicationIcon } from "@/components/bs-icons/newApplication";
import { useTranslation } from "react-i18next";
import { bsconfirm } from "../../alerts/confirm";
import { TabsContext } from "../../contexts/tabsContext";
import { deleteChatApi, getChatsApi, postBuildInit } from "../../controllers/API";
import { getFlowApi, readOnlineFlows } from "../../controllers/API/flow";
import { FlowType, NodeType } from "../../types/flow";
import { generateUUID, validateNode } from "../../utils";
import SkillTemps from "../SkillPage/components/SkillTemps";
import ChatPanne from "./components/ChatPanne";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { useDebounce } from "../../util/hook";
import "./bc.css"
import ChatComponent from "@/components/bs-comp/chatComponent";
import { locationContext } from "@/contexts/locationContext";
import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { useMessageStore } from "@/components/bs-comp/chatComponent/messageStore";

export default function SkillChatPage() {
    const [open, setOpen] = useState(false)
    const [face, setFace] = useState(true);

    const { t } = useTranslation()

    const { flow: initFlow } = useContext(TabsContext);
    const [flow, setFlow] = useState<FlowType>(null)
    const [onlineFlows, setOnlineFlows] = useState([])
    useEffect(() => {
        readOnlineFlows().then((res) => setOnlineFlows(res.data))
    }, [])
    // 对话列表
    const { chatList, chatId, chatsRef, setChatId, addChat, deleteChat } = useChatList()
    const chatIdRef = useRef('')

    const build = useBuild()
    const { messages, loadHistoryMsg, changeChatId, destory } = useMessageStore()
    // 切换聊天内容
    const changeChatContent = async (flow, chatId) => {
        // 放前面会话会串，乖乖等 build
        // loadHistoryMsg()
        // setFlow(flow)
        await build(flow, chatId)
        loadHistoryMsg(flow.id, chatId)
        setFlow(flow)
        setChatId(chatId)
        changeChatId(chatId) // ws
        setFace(false)
    }
    // select flow(新建会话)
    const handlerSelectFlow = async (node: FlowType) => {
        // 会话ID
        chatIdRef.current = generateUUID(32)
        setOpen(false)
        // add list
        addChat({
            "flow_name": node.name,
            "flow_description": node.description,
            "flow_id": node.id,
            "chat_id": chatIdRef.current,
            "create_time": "-",
            "update_time": "-"
        })

        const flow = await getFlowApi(node.id)
        changeChatContent(flow, chatIdRef.current)
    }

    // select chat
    const handleSelectChat = useDebounce(async (chat) => {
        if (chat.chat_id === chatId) return
        chatIdRef.current = chat.chat_id
        const flow = initFlow?.id === chat.flow_id ? initFlow : await getFlowApi(chat.flow_id)
        changeChatContent(flow, chatIdRef.current)
    }, 100, false)


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

    // ws 请求数据包装
    const { tabsState } = useContext(TabsContext);
    const getWsParamData = (action, msg, data) => {
        let inputs = tabsState[flow.id].formKeysData.input_keys;
        const input = inputs.find((el: any) => !el.type)
        const inputKey = input ? Object.keys(input)[0] : '';
        const msgData = {
            chatHistory: messages,
            flow_id: flow.id,
            chat_id: chatId,
            name: flow.name,
            description: flow.description,
            inputs: {}
        } as any
        if (msg) msgData.inputs = { ...input, [inputKey]: msg }
        if (data) msgData.inputs.data = data
        if (action === 'continue') msgData.action = action
        return [msgData, inputKey]
    }

    // 应用链接
    const { appConfig } = useContext(locationContext)
    const token = localStorage.getItem("ws_token") || '';
    const wsUrl = `${appConfig.websocketHost}/api/v1/chat/${flow?.id}?type=L1&t=${token}`

    // sendmsg user name
    const sendUserName = useMemo(() => {
        if (!flow) return ''
        const node = flow.data.nodes.find(el => el.data.type === 'AutoGenUser')
        return node?.data.node.template['name'].value || ''
    }, [flow])
    return <div className="flex h-full">
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
        {
            face && !flow
                ? <div className="flex-1 chat-box h-full overflow-hidden relative">
                    <img className="w-[200px] h-[182px] mt-[86px] mx-auto" src="/application-start-logo.png" alt="" />
                    <p className="text-center text-sm text-[26px] w-[162px] whitespace-normal h-[64px] leading-[32px] text-[#111111] mx-auto mt-[20px] font-light">选择一个<b className="text-[#111111] font-semibold">对话</b>开始<b className="text-[#111111] font-semibold">文擎睿见</b></p>
                    <div className="relative z-50 w-[162px] h-[38px] bg-[#0055e3] rounded-lg text-[white] leading-[38px] flex cursor-pointer hover:bg-[#0165e6] justify-around mx-auto mt-[120px] text-[13px]" onClick={() => setOpen(true)}>
                        <span className="block my-auto ml-[4px]"><NewApplicationIcon /></span>
                        <span className="mr-[28px]">{t('chat.newChat')}</span>
                    </div>
                    {/* <div className="bc"></div> */}
                </div>
                : <div className="flex-1 chat-box h-screen relative px-6">
                    {/* {flow && <ChatPanne chatId={chatId} flow={flow} />} */}
                    <div className="absolute flex top-2 gap-2 items-center">
                        <TitleIconBg className="" id={flow.id}></TitleIconBg>
                        <span className="text-sm">{flow.name}</span>
                    </div>
                    <ChatComponent useName={sendUserName} guideWord={flow.guide_word} wsUrl={wsUrl} onBeforSend={getWsParamData} />
                </div>
        }
        {/* 选择对话技能 */}
        <SkillTemps
            flows={onlineFlows}
            title={t('chat.skillTempsTitle')}
            desc={t('chat.skillTempsDesc')}
            open={open} setOpen={setOpen}
            onSelect={handlerSelectFlow}></SkillTemps>
    </div>
};
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
            captureAndAlertRequestErrorHoc(deleteChatApi(id).then(res => {
                setChatList(oldList => oldList.filter(item => item.chat_id !== id))
            }))
        }
    }
}

/**
 * build flow
 * 校验每个节点，展示进度及结果；返回input_keys;end_of_stream断开链接
 * 主要校验节点并设置更新setTabsState的 formKeysData
 */

const useBuild = () => {
    const { toast } = useToast()
    const { setTabsState } = useContext(TabsContext);
    const { t } = useTranslation()

    // SSE 服务端推送
    async function streamNodeData(flow: FlowType, chatId: string) {
        // Step 1: Make a POST request to send the flow data and receive a unique session ID
        const { flowId } = await postBuildInit(flow, chatId);
        // Step 2: Use the session ID to establish an SSE connection using EventSource
        let validationResults = [];
        let finished = false;
        let buildEnd = false
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
                buildEnd = true
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
                toast({
                    title: parsedData.error,
                    variant: 'error',
                    description: ''
                });
            }
        };
        // Step 3: Wait for the stream to finish
        while (!finished) {
            await new Promise((resolve) => setTimeout(resolve, 100));
            finished = buildEnd // validationResults.length === flow.data.nodes.length;
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

    async function handleBuild(flow: FlowType, chatId: string) {
        try {
            const errors = flow.data.nodes.flatMap((n: NodeType) => validateNode(n, flow.data.edges))
            if (errors.length > 0) {
                return toast({
                    title: t('chat.buildError'),
                    variant: 'error',
                    description: errors
                });
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