import { useCallback, useMemo } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useRecoilState, useRecoilValue } from "recoil";
import AppAvator from "~/components/Avator";
import HeaderTitle from "~/components/Chat/HeaderTitle";
import { useAuthContext, useLocalize } from "~/hooks";
import ChatInput from "./ChatInput";
import ChatMessages from "./ChatMessages";
import { ChatEmptyState } from "./components/ChatEmptyState";
import { appConversationsState } from "./store/appSidebarAtoms";
import { currentChatState, currentRunningState } from "./store/atoms";
import useChatHelpers from "./useChatHelpers";
import { useWebSocket } from "./useWebsocket";
import { generateUUID } from "~/utils";

export default function ChatView({ data, cid, v, readOnly }) {
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
        const from = new URLSearchParams(location.search).get('from');
        const nextPath = from
            ? `/app/${chatId}/${flowId}/${flowType}?from=${from}`
            : `/app/${chatId}/${flowId}/${flowType}`;
        navigate(nextPath);
    }, [flowId, flowType, location.search, navigate, setConversations]);

    const messages = chatState?.messages || [];
    const activeConversation = useMemo(
        () => conversations.find((item) => item.id === cid),
        [conversations, cid]
    );
    const headerTitle = [activeConversation?.title, data?.name]
        .map((item) => String(item || "").trim())
        .find(Boolean) || localize('com_ui_new_chat');
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
            conversation={{ title: headerTitle, flowId: data.id, conversationId: cid, flowType: data.flow_type }}
        />
        <div className="min-h-0 flex-1 flex flex-col bg-[position:0_100%] bg-repeat-x bg-[length:10px_432px]">
            {showChatEmptyState ? (
                <div className="flex min-h-0 flex-1 flex-col">
                    <ChatEmptyState onNewChat={createNewChat} />
                </div>
            ) : (
                <div className="relative mx-auto h-full min-h-0 w-full max-w-[800px] flex-1">
                    <ChatMessages
                        useName={user?.username}
                        title={data.name}
                        logo={Logo}
                        readOnly={readOnly}
                        disabledSearch={data.flow_type === 10}
                    />
                </div>
            )}
            {!readOnly && <ChatInput v={v} readOnly={readOnly} />}
        </div>
    </div>
};
