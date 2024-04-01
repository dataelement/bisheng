import ChatInput from "./ChatInput";
import MessagePanne from "./MessagePanne";

export default function ChatComponent({useName, guideWord, wsUrl, onBeforSend}) {

    return <div className="relative h-full">
        <MessagePanne useName={useName} guideWord={guideWord}></MessagePanne>
        <ChatInput wsUrl={wsUrl} onBeforSend={onBeforSend} ></ChatInput>
    </div>
};
