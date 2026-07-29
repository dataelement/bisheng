// @ts-strict-ignore
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useRecoilState, useRecoilValue, useSetRecoilState } from "recoil";
import { ChatMessageType, FlowData } from "~/@types/chat";
import { getAssistantDetailApi, getChatHistoryApi, getDeleteFlowApi, getFlowApi } from "~/api/apps";
import { checkPermission } from "~/api/permission";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";
import store from "~/store";
import ChatView from "./ChatView";
import { appConversationsState } from "./store/appSidebarAtoms";
import { chatApiVersionState, chatIdState, chatsState, currentChatState, runningState } from "./store/atoms";
import { AppLostMessage } from "./useWebsocket";

const API_VERSION = 'v1';
const TRAFFIC_LIMIT_ERROR_CODES = new Set([429, 503, 12045]);

const getInitialChatError = (res: any) => {
    const code = Number(res?.status_code);
    if (TRAFFIC_LIMIT_ERROR_CODES.has(code)) {
        return { code: String(code), data: res?.data ?? null };
    }
    return { code: AppLostMessage, data: null };
};

export const enum FLOW_TYPES {
    WORK_FLOW = 10,
    ASSISTANT = 5,
    SKILL = 1,
}

export default function index({ chatId = '', flowId = '', shareToken = '', flowType = '', apiVersion = '', isGuestMode = false }) {
    const { conversationId: _cid, fid: _fid, type: _type } = useParams();
    const cid = _cid || chatId;
    const fid = _fid || flowId;
    const type = _type || flowType;
    const effectiveApiVersion = apiVersion || API_VERSION;
    const [readOnly] = useState(shareToken);
    const setApiVersion = useRecoilState(chatApiVersionState)[1];

    // Sync apiVersion into Recoil so useChatHelpers picks up v2 WS URLs
    useEffect(() => {
        setApiVersion(effectiveApiVersion as 'v1' | 'v2');
        return () => { setApiVersion('v1'); };
    }, [effectiveApiVersion, setApiVersion]);
    const [chats, setChats] = useRecoilState(chatsState)
    const [__, setRunningState] = useRecoilState(runningState)
    const [_, setChatId] = useRecoilState(chatIdState)
    const chatState = useRecoilValue(currentChatState)
    const conversations = useRecoilValue(appConversationsState);
    const setChatMobileHeader = useSetRecoilState(store.chatMobileHeaderState);
    const localize = useLocalize();
    const navigate = useNavigate()
    const { showToast } = useToastContext()

    const flow = chatState?.flow;
    const headerTitleForMobile = useMemo(() => {
        if (!cid) return localize("com_ui_new_chat");
        const activeConversation = conversations.find((item) => item.id === cid);
        return (
            [activeConversation?.title, flow?.name]
                .map((item) => String(item || "").trim())
                .find(Boolean) || localize("com_ui_new_chat")
        );
    }, [cid, conversations, flow?.name, localize]);

    const hideShareForMobile = flow?.can_share !== true;

    // flow 尚未写入 Recoil 时 ChatView 不会挂载，但 AppRoot 的 MobileNav 仍需要标题（与桌面 HeaderTitle 同源字段）
    useEffect(() => {
        if (!cid || !fid || !type) return;
        setChatMobileHeader({
            title: headerTitleForMobile,
            conversationId: cid,
            flowId: flow?.id || String(fid),
            flowType: Number(flow?.flow_type ?? type) || 15,
            readOnly: !!readOnly,
            hideShare: hideShareForMobile,
        });
        return () => setChatMobileHeader(null);
    }, [
        cid,
        fid,
        type,
        flow?.id,
        flow?.flow_type,
        headerTitleForMobile,
        readOnly,
        hideShareForMobile,
        setChatMobileHeader,
    ]);

    // console.log('[chatState] :>> ', chatState);
    // console.log('[runningState] :>> ', __);
    // 切换会话
    const init = async () => {
        if (!cid) return;

        let flowData: FlowData | null = null
        let messages: ChatMessageType[] = []
        const currentData = chats[cid]
        let error: { code: string; data: any } = { code: '', data: null }

        setChatId(cid!) // 切换会话

        const numericType = Number(type);
        const ensureUseAppPermission = async (objectType: "workflow" | "assistant") => {
            if (shareToken || isGuestMode) return true;
            const permission = await checkPermission(objectType, fid!, "can_read", "use_app")
                .catch(() => ({ allowed: false }));
            if (permission?.allowed) return true;
            showToast?.({ message: '无访问权限，请联系管理员', severity: NotificationSeverity.ERROR });
            navigate('/apps', { replace: true });
            return false;
        };

        // Skill (flow_type=1) was removed with the legacy skill module — any deep
        // link redirects before permission checks or cache short-circuits.
        if (numericType === FLOW_TYPES.SKILL) {
            navigate('/404', { replace: true });
            return;
        }

        if (numericType === FLOW_TYPES.WORK_FLOW && !(await ensureUseAppPermission("workflow"))) return;
        if (numericType === FLOW_TYPES.ASSISTANT && !(await ensureUseAppPermission("assistant"))) return;

        if (currentData) { // 有缓存不重复加载
            return
        };

        switch (numericType) {
            case FLOW_TYPES.WORK_FLOW:
                // Fetch detail and chat history, skip global 403 redirect
                const [flowRes, msgRes] = await Promise.all([
                    getFlowApi(fid!, effectiveApiVersion, shareToken, true),
                    getChatHistoryApi({ flowId: fid, chatId: cid, flowType: type, shareToken, apiVersion: effectiveApiVersion })
                ])

                // Handle 403: no permission, redirect to app center
                if (flowRes.status_code === 403) {
                    showToast?.({ message: '无访问权限，请联系管理员', severity: NotificationSeverity.ERROR });
                    navigate('/apps', { replace: true });
                    return;
                }

                if (flowRes.status_code !== 200) {
                    error = getInitialChatError(flowRes)
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
                break;
            case FLOW_TYPES.ASSISTANT:
                // Fetch assistant detail, skip global 403 redirect
                const [assistantRes, historyRes] = await Promise.all([
                    getAssistantDetailApi(fid, shareToken, true, effectiveApiVersion),
                    getChatHistoryApi({ flowId: fid, chatId: cid, flowType: type, shareToken, apiVersion: effectiveApiVersion })
                ]);

                // Handle 403: no permission, redirect to app center
                if (assistantRes.status_code === 403) {
                    showToast?.({ message: '无访问权限，请联系管理员', severity: NotificationSeverity.ERROR });
                    navigate('/apps', { replace: true });
                    return;
                }

                if (assistantRes.status_code !== 200) {
                    error = getInitialChatError(assistantRes);
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

    return <ChatView data={chatState.flow} cid={cid} v={effectiveApiVersion} readOnly={readOnly} isGuestMode={isGuestMode} />
};
