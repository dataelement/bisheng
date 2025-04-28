import ChatInput from "./ChatInput";
import MessagePanne from "./MessagePanne";

export default function ChatComponent({
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
    loadMore = () => { }
}) {

    return <div className="relative h-full">
        <MessagePanne logo={logo} debug={debug} useName={useName} guideWord={guideWord} loadMore={loadMore}></MessagePanne>
        <ChatInput clear={clear} questions={questions} form={form} wsUrl={wsUrl} inputForm={inputForm} onBeforSend={onBeforSend} onClickClear={onClickClear}></ChatInput>
    </div>
};
