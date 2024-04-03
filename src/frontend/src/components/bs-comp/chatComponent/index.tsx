import ChatInput from "./ChatInput";
import MessagePanne from "./MessagePanne";

export default function ChatComponent({form = false, useName, inputForm = null, guideWord, wsUrl, onBeforSend, loadMore = () => {}}) {

    return <div className="relative h-full">
        <MessagePanne useName={useName} guideWord={guideWord} loadMore={loadMore}></MessagePanne>
        <ChatInput form={form} wsUrl={wsUrl} inputForm={inputForm} onBeforSend={onBeforSend} ></ChatInput>
    </div>
};
