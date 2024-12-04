import { useState } from "react";
import ChatInput from "./ChatInput";
import ChatMessages from "./ChatMessages";

export default function Chat({
    stop = false,
    logo = '',
    clear = false,
    form = false,
    useName,
    inputForm = null,
    guideWord,
    wsUrl,
    onBeforSend,
    loadMore = () => { }
}) {
    const [loading, setLoading] = useState(true)

    return <div className="relative h-full bs-chat-bg" style={{ backgroundImage: `url(${__APP_ENV__.BASE_URL}/points.png)` }}>
        <ChatMessages logo={logo} useName={useName} guideWord={guideWord} loadMore={loadMore}></ChatMessages>
        <ChatInput clear={clear} form={form} wsUrl={wsUrl} inputForm={inputForm} onBeforSend={onBeforSend} onLoad={() => setLoading(false)} ></ChatInput>
        {loading && <div className="absolute top-0 left-0 w-full h-full flex items-center justify-center bg-primary/5 z-10">
            <img className="w-[138px]" src="/application-start-logo.png" alt="" />
        </div>}
    </div>
};
