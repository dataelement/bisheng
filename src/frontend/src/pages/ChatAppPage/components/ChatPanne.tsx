
import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import ChatComponent from "@/components/bs-comp/chatComponent";
import { useMessageStore } from "@/components/bs-comp/chatComponent/messageStore";
import { AssistantIcon } from "@/components/bs-icons/assistant";
import { NewApplicationIcon } from "@/components/bs-icons/newApplication";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { locationContext } from "@/contexts/locationContext";
import { useAssistantStore } from "@/store/assistantStore";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { TabsContext } from "../../../contexts/tabsContext";
import { postBuildInit } from "../../../controllers/API";
import { Variable, getFlowApi } from "../../../controllers/API/flow";
import { FlowType, NodeType } from "../../../types/flow";
import { validateNode } from "../../../utils";
import ChatReportForm from "../components/ChatReportForm";

export default function ChatPanne({ customWsHost = '', data }) {
    const { id, chatId, type } = data
    const { t } = useTranslation()

    const [flow, setFlow] = useState<any>(null)
    const flowRef = useRef(null)
    const [assistant, setAssistant] = useState<any>(null)
    const { assistantState, loadAssistantState } = useAssistantStore()
    // console.log('data :>> ', flow);
    const build = useBuild()
    const { messages, loadHistoryMsg, loadMoreHistoryMsg, changeChatId, destory } = useMessageStore()

    const init = async () => {
        if (type === 'flow') {
            setAssistant(null)
            const _flow = await getFlowApi(id)
            await build(_flow, chatId)
            loadHistoryMsg(_flow.id, chatId)
            flowRef.current = _flow
            setFlow(_flow)
            changeChatId(chatId) // ws
        } else {
            flowRef.current = null
            setFlow(null)
            const _assistant = await loadAssistantState(id)
            loadHistoryMsg(_assistant.id, chatId)
            setAssistant(_assistant)
            changeChatId(chatId) // ws
        }
    }
    useEffect(() => {
        if (!id) {
            flowRef.current = null
            setFlow(null)
            setAssistant(null)
            return
        }
        init()
    }, [data])



    // ws 请求数据包装
    const { tabsState } = useContext(TabsContext);
    // 依赖 chatId更新闭包，不依赖 flow
    const getWsParamData = (action, msg) => {
        if (type === 'flow') {
            const _flow = flowRef.current
            let inputs = tabsState[_flow.id].formKeysData.input_keys;
            const input = inputs.find((el: any) => !el.type)
            const inputKey = input ? Object.keys(input)[0] : '';
            const msgData = {
                chatHistory: messages,
                flow_id: _flow.id,
                chat_id: chatId,
                name: _flow.name,
                description: _flow.description,
                inputs: {}
            } as any
            if (msg) msgData.inputs = { ...input, [inputKey]: msg }
            if (formDataRef.current?.length) {
                msgData.inputs.data = formDataRef.current
                formDataRef.current = null
            }
            if (action === 'continue') msgData.action = action
            return [msgData, inputKey]
        } else {
            const inputKey = 'input';
            const msgData = {
                chatHistory: messages,
                flow_id: '',
                chat_id: chatId,
                name: assistant.name,
                description: assistant.desc,
                inputs: {}
            } as any
            if (msg) msgData.inputs = { [inputKey]: msg }
            if (data) msgData.inputs.data = data
            if (action === 'continue') msgData.action = action
            return [msgData, inputKey]
        }
    }

    // 应用链接
    const { appConfig } = useContext(locationContext)
    const token = localStorage.getItem("ws_token") || '';
    let wsUrl = type === 'flow' ? `${appConfig.websocketHost}/api/v1/chat/${flowRef.current?.id}?type=L1&t=${token}` :
        `${location.host}/api/v1/assistant/chat/${assistant?.id}?t=${token}`

    if (customWsHost) {
        wsUrl = `${appConfig.websocketHost}${customWsHost}&t=${token}`
    }

    // sendmsg user name
    const sendUserName = useMemo(() => {
        if (!flow) return ''
        const node = flow.data.nodes.find(el => el.data.type === 'AutoGenUser')
        return node?.data.node.template['name'].value || ''
    }, [flow])

    const flowSate = useMemo(() => {
        if (!flow) return { isRoom: false, isForm: false, isReport: false }
        // 是否群聊
        const isRoom = !!flow.data?.nodes.find(node => node.data.type === "AutoGenChain")
        // 是否展示表单
        const isForm = !!flow.data?.nodes.find(node => ["VariableNode", "InputFileNode"].includes(node.data.type))
        // 是否报表
        const isReport = !!flow.data?.nodes.find(node => "Report" === node.data.type)
        return { isRoom, isForm, isReport }
    }, [flow])

    // 发送表单 (提交-》event触发发送-》getWsParamData获取参数时追加 data)
    const formDataRef = useRef<any>(null)
    const sendReport = (items: Variable[], str) => {

        formDataRef.current = items.map(item => ({
            id: item.nodeId,
            name: item.name,
            file_path: item.type === 'file' ? item.value : '',
            value: item.type === 'file' ? '' : item.value
        }))

        const myEvent = new CustomEvent('userResendMsgEvent', {
            detail: {
                send: true,
                message: str
            }
        });
        document.dispatchEvent(myEvent);
    }

    if (!(flow || assistant)) return <div className="flex-1 chat-box h-full overflow-hidden bs-chat-bg">
        <img className="w-[200px] h-[182px] mt-[86px] mx-auto" src="/application-start-logo.png" alt="" />
        <p className="text-center text-3xl w-[182px] whitespace-normal leading-[64px] text-[#111111] mx-auto mt-[20px] font-light">
            选择一个<b className="text-[#111111] font-semibold">对话</b><br />开始<b className="text-[#111111] font-semibold">文擎睿见</b>
        </p>
        {
            !customWsHost && <div
                className="relative z-50 w-[162px] h-[38px] bg-[#0055e3] rounded-lg text-[white] leading-[38px] flex cursor-pointer hover:bg-[#0165e6] justify-around mx-auto mt-[120px] text-[13px]"
                onClick={() => {
                    document.getElementById('newchat')?.click()
                }}>
                <span className="block my-auto ml-[4px]"><NewApplicationIcon /></span>
                <span className="mr-[28px]">{t('chat.newChat')}</span>
            </div>
        }
    </div>


    return <div className="flex-1 min-w-0 min-h-0 bs-chat-bg">
        {/* 技能会话 */}
        {
            flow && <div className={`w-full chat-box h-full relative px-6 ${type === 'flow' ? 'block' : 'hidden'}`}>
                {/* {flow && <ChatPanne chatId={chatId} flow={flow} />} */}
                <div className="absolute flex top-2 gap-2 items-center z-10 bg-[rgba(255,255,255,0.8)] px-2 py-1">
                    <TitleIconBg className="" id={flow.id}></TitleIconBg>
                    <span className="text-sm">{flow.name}</span>
                </div>
                <ChatComponent
                    form={flowSate.isForm}
                    useName={sendUserName}
                    guideWord={flow.guide_word}
                    wsUrl={wsUrl}
                    onBeforSend={getWsParamData}
                    loadMore={() => loadMoreHistoryMsg(flow.id)}
                    inputForm={flowSate.isForm ? <ChatReportForm flow={flow} onStart={sendReport} /> : null}
                />
            </div>
        }
        {/* 助手会话 */}
        {
            assistant && <div className={`w-full chat-box h-full relative px-6 ${type !== 'flow' ? 'block' : 'hidden'}`}>
                {/* {flow && <ChatPanne chatId={chatId} flow={flow} />} */}
                <div className="absolute flex top-2 gap-2 items-center z-10 bg-[rgba(255,255,255,0.8)] px-2 py-1">
                    <TitleIconBg className="" id={assistant.id}><AssistantIcon /></TitleIconBg>
                    <span className="text-sm">{assistant.name}</span>
                </div>
                <ChatComponent
                    useName={sendUserName}
                    questions={assistantState.guide_question.filter((item) => item)}
                    guideWord={assistantState.guide_word}
                    wsUrl={wsUrl}
                    onBeforSend={getWsParamData}
                    loadMore={() => loadMoreHistoryMsg(assistant.id)}
                    inputForm={null}
                />
            </div>
        }
    </div>
};


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