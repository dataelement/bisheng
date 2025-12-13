import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useRecoilState, useRecoilValue } from "recoil";
import { ChatMessageType, FlowData } from "~/@types/chat";
import { getAssistantDetailApi, getChatHistoryApi, getDeleteFlowApi, getFlowApi, postBuildInit } from "~/api/apps";
import { useToastContext } from "~/Providers";
import ChatView from "./ChatView";
import { chatIdState, chatsState, currentChatState, runningState, tabsState } from "./store/atoms";
import { AppLostMessage } from "./useWebsocket";

const API_VERSION = 'v1';
export const enum FLOW_TYPES {
    WORK_FLOW = 10,
    ASSISTANT = 5,
    SKILL = 1,
}

export default function index({ chatId = '', flowId = '', shareToken = '', flowType = '' }) {
    const { conversationId: _cid, fid: _fid, type: _type } = useParams();
    const cid = _cid || chatId;
    const fid = _fid || flowId;
    const type = _type || flowType;
    const [readOnly] = useState(shareToken);
    const [chats, setChats] = useRecoilState(chatsState)
    const [__, setRunningState] = useRecoilState(runningState)
    const [_, setChatId] = useRecoilState(chatIdState)
    const chatState = useRecoilValue(currentChatState)
    const build = useBuild()

    // console.log('[chatState] :>> ', chatState);
    // console.log('[runningState] :>> ', __);
    // 切换会话
    const init = async () => {
        if (!cid) return;

        let flowData: FlowData | null = null
        let messages: ChatMessageType[] = []
        const currentData = chats[cid]
        let error = { code: '', data: null }

        setChatId(cid!) // 切换会话

        const numericType = Number(type);

        if (currentData) { // 有缓存不重复加载
            numericType === FLOW_TYPES.SKILL && setRunningState((prev) => {
                // 技能重置输入框状态
                return {
                    ...prev,
                    [cid]: {
                        ...(prev?.[cid] || {}),
                        inputDisabled: false,
                    },
                };
            })
            return
        };

        switch (numericType) {
            case FLOW_TYPES.SKILL:
            case FLOW_TYPES.WORK_FLOW:
                // 获取详情和历史消息
                const [flowRes, msgRes] = await Promise.all([
                    getFlowApi(fid!, API_VERSION, shareToken),
                    getChatHistoryApi({ flowId: fid, chatId: cid, flowType: type, shareToken })
                ])

                if (flowRes.status_code !== 200) {
                    error = { code: AppLostMessage, data: null }
                    const lostFlow = await getDeleteFlowApi(cid)
                    flowRes.data = {
                        id: lostFlow.data.flow_id,
                        name: lostFlow.data.flow_name,
                        logo: lostFlow.data.flow_logo,
                        flow_type: lostFlow.data.flow_type,
                    }
                }
                messages = msgRes.reverse()
                flowData = { ...flowRes.data, isNew: !messages.length }

                // 插入分割线
                // if (messages.length) {
                //     messages.push({
                //         ...baseMsgItem,
                //         id: Math.random() * 1000000,
                //         category: 'divider',
                //         message: '以上为历史消息',
                //     })
                // }
                if (numericType === FLOW_TYPES.SKILL) {
                    try {
                        await build(flowData, cid);
                    } catch (error) { }
                }
                break;
            case FLOW_TYPES.ASSISTANT:
                const [assistantRes, historyRes] = await Promise.all([
                    getAssistantDetailApi(fid, shareToken),
                    getChatHistoryApi({ flowId: fid, chatId: cid, flowType: type, shareToken })
                ]);

                if (assistantRes.status_code !== 200) {
                    error = { code: AppLostMessage, data: null };
                    const lostFlow = await getDeleteFlowApi(cid)
                    assistantRes.data = {
                        name: lostFlow.data.flow_name,
                        logo: lostFlow.data.flow_logo,
                        flow_type: lostFlow.data.flow_type,
                    }
                }
                messages = historyRes.reverse();
                flowData = { ...assistantRes.data, flow_type: FLOW_TYPES.ASSISTANT, isNew: !messages.length };
                break;
            default:
        }

        setChats(prevChats => ({
            ...prevChats,
            [cid]: {
                flow: flowData,
                messages,
                historyEnd: false
            }
        }));

        if (shareToken) {
            error = { code: '', data: null }
        }
        // 更新状态
        // !!flow.data?.nodes.find(node => ["VariableNode", "InputFileNode"].includes(node.data.type))
        setRunningState((prev) => {
            return {
                ...prev,
                [cid]: {
                    running: false,
                    inputDisabled: error.code || numericType === FLOW_TYPES.WORK_FLOW,
                    error,
                    inputForm: numericType !== FLOW_TYPES.WORK_FLOW || null,
                    showUpload: numericType === FLOW_TYPES.WORK_FLOW,
                    showStop: false,
                    guideWord: flowData?.guide_question,
                    showReRun: false
                }
            }
        })

    }

    useEffect(() => {
        init()
    }, [cid])

    if (!cid || !chatState?.flow) return null;

    return <ChatView data={chatState.flow} cid={cid} v={API_VERSION} readOnly={readOnly} />
};

/**
 * build flow
 * 校验每个节点，展示进度及结果；返回input_keys;end_of_stream断开链接
 * 主要校验节点并设置更新setTabsState的 formKeysData
 */

const useBuild = () => {
    const { showToast } = useToastContext();
    const [_, setTabsState] = useRecoilState(tabsState)

    // SSE 服务端推送
    async function streamNodeData(flow: any, chatId: string) {
        // Step 1: Make a POST request to send the flow data and receive a unique session ID
        const res = await postBuildInit({ flow, chatId });
        const flowId = res.data.flowId;
        // Step 2: Use the session ID to establish an SSE connection using EventSource
        let validationResults = [];
        let finished = false;
        let buildEnd = false
        const apiUrl = `${__APP_ENV__.BASE_URL}/api/v1/build/stream/${flowId}?chat_id=${chatId}`;
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
            buildEnd = true
            console.error("EventSource failed:", error);
            eventSource.close();
            // if (error.data) {
            //     const parsedData = JSON.parse(error.data);
            //     showToast({ message: parsedData.error, status: 'error' });
            // }
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

    async function handleBuild(flow: any, chatId: string) {
        try {
            // const errors = flow.data.nodes.flatMap((n) => validateNode(n, flow.data.edges))
            // if (errors.length > 0) {
            //     return showToast({ message: errors.join('\n'), status: 'error' });
            // }

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