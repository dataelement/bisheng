import { useMemo } from "react";
import { useLocation } from "react-router-dom";
import { useRecoilValue } from "recoil";
import AppAvator from "~/components/Avator";
import HeaderTitle from "~/components/Chat/HeaderTitle";
import { useAuthContext } from "~/hooks";
import ChatInput from "./ChatInput";
import ChatMessages from "./ChatMessages";
import { ChatEmptyState } from "./components/ChatEmptyState";
import { useAppSidebar } from "./hooks/useAppSidebar";
import { currentChatState } from "./store/atoms";
import useChatHelpers from "./useChatHelpers";
import { useWebSocket } from "./useWebsocket";

export default function ChatView({ data, cid, v, readOnly }) {
    const { user } = useAuthContext();
    const help = useChatHelpers()
    useWebSocket(help)

    const location = useLocation();
    const chatState = useRecoilValue(currentChatState);
    const { createNewChat } = useAppSidebar();
    const messages = chatState?.messages || [];

    // Only show empty state when navigated from continueChat with no history
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- router state untyped
    const showEmpty = !!(location.state as any)?.emptyHistory && messages.length === 0;

    const Logo = useMemo(() => {
        return <AppAvator className="size-6 min-w-6" url={data.logo} id={data.name} flowType={data.flow_type} />
    }, [data]);

    return <div className="relative h-full flex flex-col">
        {!showEmpty && (
            <HeaderTitle
                readOnly={readOnly}
                conversation={{ title: data.name, flowId: data.id, conversationId: cid, flowType: data.flow_type }}
            />
        )}
        <div className="min-h-0 flex-1 bg-[position:0_100%] bg-repeat-x bg-[length:10px_432px]">
            {showEmpty ? (
                <ChatEmptyState onNewChat={createNewChat} />
            ) : (
                <div className="relative h-full max-w-[860px] mx-auto">
                    <ChatMessages
                        useName={user?.username}
                        title={data.name}
                        logo={Logo}
                        readOnly={readOnly}
                        disabledSearch={data.flow_type === 10}
                    />
                    {!readOnly && <ChatInput v={v} readOnly={readOnly} />}
                </div>
            )}
        </div>
    </div>
};
