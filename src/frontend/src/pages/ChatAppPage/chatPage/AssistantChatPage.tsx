import { userContext } from "@/contexts/userContext";
import { useContext, useState } from "react";
import { useParams } from "react-router-dom";
import ChatPanne from "../components/ChatPanne";

export default function AssistantChatPage() {
    const { id: flowId } = useParams()
    const { user } = useContext(userContext);

    const [data] = useState<any>({ id: flowId, chatId: `${flowId}_${user.user_id}`, type: 'assistant' })

    if (!flowId) return <div>请选择会话</div>

    return <ChatPanne data={data} />
};
