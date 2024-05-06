import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import ChatComponent from "@/components/bs-comp/chatComponent";
import { useMessageStore } from "@/components/bs-comp/chatComponent/messageStore";
import { AssistantIcon } from "@/components/bs-icons/assistant";
import { useAssistantStore } from "@/store/assistantStore";
import { useEffect } from "react";

export default function TestChat({ assisId, guideQuestion }) {
    const token = localStorage.getItem("ws_token") || '';
    const wsUrl = `${location.host}/api/v1/assistant/chat/${assisId}?t=${token}`

    const { messages, changeChatId } = useMessageStore()
    const { assistantState } = useAssistantStore()

    // 编辑页生成唯一id
    // const chatIdRef = useRef(generateUUID(32))
    useEffect(() => {
        // 建立 websocket
        changeChatId('')
    }, [])

    // send 前获取参数用来做 params to send ws
    const getWsParamData = (action, msg, data) => {
        const inputKey = 'input';
        const msgData = {
            chatHistory: messages,
            flow_id: '',
            chat_id: '',
            name: assistantState.name,
            description: assistantState.desc,
            inputs: {}
        } as any
        if (msg) msgData.inputs = { [inputKey]: msg }
        if (data) msgData.inputs.data = data
        if (action === 'continue') msgData.action = action
        return [msgData, inputKey]
    }

    return <div className="relative h-full px-4 bs-chat-bg">
        <div className="absolute flex left-0 top-0 gap-2 px-4 py-2 items-center z-10 bg-[#fff] shadow-sm">
            <TitleIconBg className="" id={assistantState.id}><AssistantIcon /></TitleIconBg>
            <span className="text-sm ">调试预览</span>
        </div>
        <ChatComponent
            clear
            questions={guideQuestion}
            useName=''
            guideWord=''
            wsUrl={wsUrl}
            onBeforSend={getWsParamData}
        ></ChatComponent>
    </div>
};
