import { useMemo } from "react";
import AppAvator from "~/components/Avator";
import HeaderTitle from "~/components/Chat/HeaderTitle";
import { useAuthContext } from "~/hooks";
import ChatInput from "./ChatInput";
import ChatMessages from "./ChatMessages";
import useChatHelpers from "./useChatHelpers";
import { useWebSocket } from "./useWebsocket";

export default function ChatView({ data, cid, v, readOnly }) {
    const { user } = useAuthContext();
    const help = useChatHelpers()
    useWebSocket(help)

    const Logo = useMemo(() => {
        return <AppAvator className="size-6 min-w-6" url={data.logo} id={data.name} flowType={data.flow_type} />
    }, [data]);

    return <div className="relative h-full flex flex-col">
        {/* <div className="absolute flex top-2 gap-2 items-center z-10 bg-[rgba(255,255,255,0.8)] px-6 py-1 dark:bg-[#1B1B1B]">
            {Logo}
            <span className="text-sm">{data.name}</span>
        </div> */}
        <HeaderTitle
            readOnly={readOnly}
            conversation={{ title: data.name, flowId: data.id, conversationId: cid, flowType: data.flow_type }}
            logo={Logo}
        />
        <div className="min-h-0 flex-1 bg-[position:0_100%] bg-repeat-x bg-[length:10px_432px]"
        // style={{ backgroundImage: `url(${__APP_ENV__.BASE_URL}/assets/points.png)` }}
        >
            <div className="relative h-full max-w-[860px] mx-auto">
                <ChatMessages
                    useName={user?.username}
                    title={data.name}
                    logo={Logo}
                    readOnly={readOnly}
                    disabledSearch={data.flow_type === 10}
                />
                <ChatInput v={v} readOnly={readOnly} />
            </div>
        </div>
    </div>
};

