// 嵌iframe、适配移动端(企业接入)
import { useContext, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import ChatPanne from "./components/ChatPanne";
import { userContext } from "@/contexts/userContext";

export default function ChatPro({ type = 'flow' }) {
    const { id: flowId } = useParams()
    const { user } = useContext(userContext);

    const [data, setData] = useState<any>(null)
    // c41f9bb3-966e-4ded-9f3f-9077f70bc707
    useEffect(() => {
        // sdk 获取用户
        setData({ id: flowId, chatId: `${flowId.replaceAll('-', '')}_${user.user_id}`, type })
    }, [])

    if (!flowId) return <div>请选择会话</div>
    if (!data) return null

    return <ChatPanne data={data} />
};
