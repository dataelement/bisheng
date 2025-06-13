import { useState } from "react";
import ChatInput from "./ChatInput";
import ChatMessages from "./ChatMessages";
import { LoadingIcon } from "@/components/bs-icons/loading";

export default function Chat({
    stop = false,
    debug,
    autoRun,
    logo = '',
    clear = false,
    form = false,
    useName,
    inputForm = null,
    guideWord,
    wsUrl,
    onBeforSend,
    flow,
    loadMore = () => { }
}) {
    const [loading, setLoading] = useState(autoRun)

    return <div className="h-full bs-chat-bg" style={{ backgroundImage: `url(${__APP_ENV__.BASE_URL}/points.png)` }}>
        <div className="relative h-full">
            <ChatMessages flow={flow} debug={debug} logo={logo} useName={useName} guideWord={guideWord} loadMore={loadMore}></ChatMessages>
            <ChatInput flow={flow} autoRun={autoRun} clear={clear} form={form} wsUrl={wsUrl} inputForm={inputForm} onBeforSend={onBeforSend} onLoad={() => setLoading(false)} ></ChatInput>
        </div>
        {loading && <div className="absolute top-0 left-0 w-full h-full flex items-center justify-center bg-primary/5 z-10">
            <LoadingIcon className="size-24" />
        </div>}
    </div>
};
