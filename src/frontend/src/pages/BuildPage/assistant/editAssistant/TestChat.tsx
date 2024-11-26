import { TitleLogo } from "@/components/bs-comp/cardComponent";
import ChatComponent from "@/components/bs-comp/chatComponent";
import { useMessageStore } from "@/components/bs-comp/chatComponent/messageStore";
import { AssistantIcon } from "@/components/bs-icons";
import { useAssistantStore } from "@/store/assistantStore";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

export default function TestChat({ assisId, guideQuestion }) {
    const token = localStorage.getItem("ws_token") || '';
    const wsUrl = `${location.host}${__APP_ENV__.BASE_URL}/api/v1/assistant/chat/${assisId}?t=${token}`

    const { messages, changeChatId } = useMessageStore()
    const { assistantState } = useAssistantStore()
    const { t } = useTranslation()

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
            flow_id: data?.id || assisId,
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

    return <div className="relative h-full px-4 bs-chat-bg bg-background-login" style={{ backgroundImage: `url(${__APP_ENV__.BASE_URL}/points.png)` }}>
        <div className="absolute flex w-full left-0 top-0 gap-2 px-4 py-2 items-center z-10 bg-background-login shadow-sm">
            <TitleLogo
                url={assistantState.logo}
                id={assistantState.id}
            ><AssistantIcon /></TitleLogo>
            <span className="text-sm ">{t('build.debugPreview')}</span>
        </div>
        <ChatComponent
            clear
            logo={assistantState.logo}
            questions={guideQuestion}
            useName=''
            guideWord=''
            wsUrl={wsUrl}
            onBeforSend={getWsParamData}
        ></ChatComponent>
    </div>
};
