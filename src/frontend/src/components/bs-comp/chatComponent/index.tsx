import ChatInput from "./ChatInput";
import MessagePanne from "./MessagePanne";

export default function ChatComponent({useName, inputForm = null, guideWord, wsUrl, onBeforSend, loadMore = () => {}}) {

    return <div className="relative h-full">
        <MessagePanne useName={useName} guideWord={guideWord} loadMore={loadMore}></MessagePanne>
        <ChatInput wsUrl={wsUrl} inputForm={inputForm} onBeforSend={onBeforSend} ></ChatInput>
    </div>
};
