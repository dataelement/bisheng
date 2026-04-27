import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useRecoilState, useRecoilValue, useSetRecoilState } from "recoil";
import AppAvator from "~/components/Avator";
import HeaderTitle from "~/components/Chat/HeaderTitle";
import { useCitationReferencePanel } from "~/components/Chat/Messages/Content/useCitationReferencePanel";
import { useAuthContext, useLocalize } from "~/hooks";
import usePrefersMobileLayout from "~/hooks/usePrefersMobileLayout";
import store from "~/store";
import ChatInput from "./ChatInput";
import ChatMessages from "./ChatMessages";
import { ChatEmptyState } from "./components/ChatEmptyState";
import { appConversationsState } from "./store/appSidebarAtoms";
import { currentChatState, currentRunningState } from "./store/atoms";
import useChatHelpers from "./useChatHelpers";
import { useWebSocket } from "./useWebsocket";
import { generateUUID } from "~/utils";

export default function ChatView({ data, cid, v, readOnly, isGuestMode = false }) {
    const { user } = useAuthContext();
    const help = useChatHelpers()
    useWebSocket(help)

    const localize = useLocalize();
    const navigate = useNavigate();
    const location = useLocation();
    const { fid: flowId, type: flowType } = useParams();
    const chatState = useRecoilValue(currentChatState);
    const running = useRecoilValue(currentRunningState);
    const conversations = useRecoilValue(appConversationsState);
    const [, setConversations] = useRecoilState(appConversationsState);
    const setChatMobileHeader = useSetRecoilState(store.chatMobileHeaderState);
    const isTabletOrMobile = usePrefersMobileLayout();

    // Lightweight createNewChat — avoids importing useAppSidebar which would
    // spin up a second auto-fetch/auto-select effect and overwrite placeholders.
    const createNewChat = useCallback(() => {
        if (!flowId || !flowType) return;
        const chatId = generateUUID(32);
        setConversations((prev) => [{
            id: chatId,
            title: localize('com_ui_new_chat'),
            flowId: flowId,
            flowType: Number(flowType),
            updatedAt: new Date().toISOString(),
            createdAt: new Date().toISOString(),
        }, ...prev]);
        const qs = location.search || '';
        const nextPath = `/app/${chatId}/${flowId}/${flowType}${qs}`;
        navigate(nextPath);
    }, [flowId, flowType, localize, location.search, navigate, setConversations]);

    const messages = chatState?.messages || [];
    const hasMessages = messages.length > 0;
    const { activeCitationMessageId, citationPanelElement, onOpenCitationPanel } = useCitationReferencePanel({ hasMessages });
    const activeConversation = useMemo(
        () => conversations.find((item) => item.id === cid),
        [conversations, cid]
    );
    const headerTitle = [activeConversation?.title, data?.name]
        .map((item) => String(item || "").trim())
        .find(Boolean) || localize('com_ui_new_chat');

    /** 与侧栏「分享应用」一致：仅 can_share === true 时展示对话顶栏分享入口 */
    const hideShare = data?.can_share !== true;

    useEffect(() => {
        setChatMobileHeader({
            title: headerTitle,
            conversationId: cid || '',
            flowId: data?.id || '',
            flowType: data?.flow_type || 15,
            readOnly: !!readOnly,
            hideShare,
        });
        return () => setChatMobileHeader(null);
    }, [setChatMobileHeader, headerTitle, cid, data?.id, data?.flow_type, readOnly, hideShare]);
    /** 无消息且无需展示开场白 / 引导问题 / 工作流表单时显示主区域空状态 */
    const showChatEmptyState =
        conversations.length === 0 &&
        messages.length === 0 &&
        !data?.guide_word &&
        !running?.inputForm &&
        !(running?.guideWord?.length);

    const Logo = useMemo(() => {
        return <AppAvator className="size-6 min-w-6" url={data.logo} id={data.name} flowType={data.flow_type} />
    }, [data]);

    return <div className="relative h-full flex flex-col">
        <HeaderTitle
            readOnly={readOnly}
            hideShare={hideShare}
            conversation={{ title: headerTitle, flowId: data.id, conversationId: cid, flowType: data.flow_type }}
        />
        <div className="min-h-0 flex-1 flex flex-col bg-[position:0_100%] bg-repeat-x bg-[length:10px_432px]">
            {showChatEmptyState ? (
                <div className="flex min-h-0 flex-1 flex-col">
                    <ChatEmptyState onNewChat={createNewChat} />
                </div>
            ) : (
                <div className="flex min-h-0 flex-1 overflow-hidden">
                    <div className="relative min-w-0 flex-1 min-h-0 overflow-hidden">
                        <div className="relative mx-auto h-full min-h-0 w-full max-w-[800px] flex-1">
                            <ChatMessages
                                useName={user?.username}
                                title={data.name}
                                logo={Logo}
                                readOnly={readOnly}
                                isGuestMode={isGuestMode}
                                disabledSearch={data.flow_type === 10}
                                onOpenCitationPanel={onOpenCitationPanel}
                                activeCitationMessageId={activeCitationMessageId}
                            />
                        </div>
                    </div>

                    {citationPanelElement}
                </div>
            )}
            {!readOnly && <ChatInput v={v} readOnly={readOnly} />}
        </div>
    </div>
};
