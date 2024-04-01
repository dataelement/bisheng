import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import ChatComponent from "@/components/bs-comp/chatComponent";
import { useMessageStore } from "@/components/bs-comp/chatComponent/messageStore";
import { useAssistantStore } from "@/store/assistantStore";
import { useEffect, useRef } from "react";

export default function TestChat({ assisId }) {
    const token = localStorage.getItem("ws_token") || '';
    const wsUrl = `${location.host}/api/v1/assistant/chat/${assisId}?t=${token}`

    const { messages, changeChatId } = useMessageStore()
    const { assistantState } = useAssistantStore()

    // TODO DEL
    const chatIdRef = useRef('xxxxkkkiiixxxxkkkiiixxxxkkkiiidd')
    useEffect(() => {
        // 建立 websocket
        changeChatId(chatIdRef.current)
    }, [])

    const getWsParamData = (action, msg, data) => {
        const inputKey = 'input';
        const msgData = {
            chatHistory: messages,
            flow_id: '',
            chat_id: chatIdRef.current,
            name: assistantState.name,
            description: assistantState.desc,
            inputs: {}
        } as any
        if (msg) msgData.inputs = { [inputKey]: msg }
        if (data) msgData.inputs.data = data
        if (action === 'continue') msgData.action = action
        return [msgData, inputKey]
    }

    return <div className="relative h-full px-4">
        <div className="absolute flex top-2 gap-2 items-center">
            <TitleIconBg className="" id={assistantState.id}></TitleIconBg>
            <span className="text-sm">{assistantState.name}</span>
        </div>
        <ChatComponent useName='' guideWord='' wsUrl={wsUrl} onBeforSend={getWsParamData}></ChatComponent>
    </div>
};
