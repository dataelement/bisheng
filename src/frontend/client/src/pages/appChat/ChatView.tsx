import { useMemo } from "react";
import AppAvator from "~/components/Avator";
import { useAuthContext } from "~/hooks";
import ChatInput from "./ChatInput";
import ChatMessages from "./ChatMessages";
import { useWebSocket } from "./useWebsocket";
import useChatHelpers from "./useChatHelpers";
import HeaderTitle from "~/components/Chat/HeaderTitle";

export default function ChatView({ data, v }) {
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
        <HeaderTitle conversation={{ title: data.name }} logo={Logo} />
        <div className="min-h-0 flex-1 bg-[position:0_100%] bg-repeat-x bg-[length:10px_432px]"
        // style={{ backgroundImage: `url(${__APP_ENV__.BASE_URL}/assets/points.png)` }}
        >
            <div className="relative h-full max-w-[860px] mx-auto">
                <ChatMessages useName={user?.username} title={data.name} logo={Logo} />
                <ChatInput v={v} />
            </div>
        </div>
    </div>
};

