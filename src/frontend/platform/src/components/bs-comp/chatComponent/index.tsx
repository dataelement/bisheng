import ChatInput from "./ChatInput";
import MessagePanne from "./MessagePanne";

export default function ChatComponent({
    showUpload = false,
    assistant = false,
    stop = false,
    debug = false,
    logo = '',
    clear = false,
    questions = [],
    form = false,
    useName,
    inputForm = null,
    guideWord,
    wsUrl,
    onBeforSend,
    onClickClear,
    flow,
    loadMore = () => { }
}) {
    return <div className="relative h-full">
        <MessagePanne flow={flow} logo={logo} debug={debug} useName={useName} guideWord={guideWord} loadMore={loadMore}></MessagePanne>
        <ChatInput showUpload={showUpload} flow={flow} assistant={assistant}  clear={clear} questions={questions} form={form} wsUrl={wsUrl} inputForm={inputForm} onBeforSend={onBeforSend} onClickClear={onClickClear}></ChatInput>
    </div>
};
